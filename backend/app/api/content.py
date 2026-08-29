"""Conteudo: criacao manual, geracao opcional por IA, aprovacao com anti-cross-posting."""

import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import current_user
from app.db import get_db
from app.api.media import attach_media
from app.models import (
    AIGeneration,
    AuditLog,
    CandidateMedia,
    ContentCandidate,
    ManualSourceText,
    MediaAsset,
    SourcePost,
    User,
    XAccount,
)
from app.services import ai, dedup

router = APIRouter(prefix="/api/content", tags=["content"])


class GenerateIn(BaseModel):
    target_x_account_id: int
    # A origem pode ser um post coletado OU um texto qualquer (ex: "Meus Textos").
    source_post_id: int | None = None
    source_text: str | None = Field(default=None, max_length=2000)
    count: int = Field(default=3, ge=1, le=5)


class CandidateIn(BaseModel):
    text: str = Field(min_length=1, max_length=280)
    target_x_account_id: int
    source_post_id: int | None = None
    origin: str = "manual"
    media_ids: list[int] = []


class BulkIn(BaseModel):
    """Monta N posts combinando aleatoriamente textos, midias e contas.

    O resultado SEMPRE entra como `pending`: nada é aprovado nem agendado
    automaticamente — a revisao humana continua obrigatoria.
    """

    text_ids: list[int] = Field(min_length=1)
    account_ids: list[int] = Field(min_length=1)
    media_ids: list[int] = []
    count: int = Field(default=0, ge=0, le=200)  # 0 = usa todos os textos
    attach_media: bool = True


class CandidateUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=280)


def media_payload(links) -> list[dict]:
    """Resumo da midia para preview na UI (usado em conteudo e na fila)."""
    out = []
    for link in sorted(links, key=lambda x: x.position):
        asset = link.asset
        if asset is None:
            continue
        out.append(
            {
                "id": asset.id,
                "kind": asset.kind,
                "url": f"/api/media/{asset.id}/file",
                "filename": asset.filename,
            }
        )
    return out


def _serialize(c: ContentCandidate, media: list[dict] | None = None) -> dict:
    return {
        "id": c.id,
        "media": media or [],
        "text": c.generated_text,
        "status": c.status,
        "origin": c.origin,
        "block_reason": c.block_reason,
        "source_post_id": c.source_post_id,
        "target_x_account_id": c.target_x_account_id,
        "account_username": c.account.username if c.account else None,
        "created_at": c.created_at,
        "approved_at": c.approved_at,
    }


async def load_media_map(db: AsyncSession, candidate_ids: list[int]) -> dict[int, list[dict]]:
    """Busca a midia de varios conteudos de uma vez (evita N+1)."""
    if not candidate_ids:
        return {}
    links = (
        await db.execute(
            select(CandidateMedia)
            .where(CandidateMedia.content_candidate_id.in_(candidate_ids))
            .order_by(CandidateMedia.position)
        )
    ).scalars().all()

    grouped: dict[int, list] = {}
    for link in links:
        grouped.setdefault(link.content_candidate_id, []).append(link)
    return {cid: media_payload(items) for cid, items in grouped.items()}


async def _check_cross_posting(
    db: AsyncSession, user_id: int, text: str, target_account_id: int
) -> dict | None:
    """Compara com conteudo recente das OUTRAS contas do usuario."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        await db.execute(
            select(ContentCandidate)
            .where(
                ContentCandidate.user_id == user_id,
                ContentCandidate.target_x_account_id != target_account_id,
                ContentCandidate.status.in_(("approved", "scheduled", "published")),
                ContentCandidate.created_at >= cutoff,
            )
            .limit(300)
        )
    ).scalars().all()

    existing = [
        (r.id, r.generated_text, r.account.username if r.account else "outra conta") for r in rows
    ]
    return dedup.find_conflict(text, existing, settings.SIMILARITY_THRESHOLD)


@router.get("/ai-status")
async def ai_status():
    """A UI usa isto para decidir se mostra o botao de IA."""
    return {"available": ai.provider.available(), "model": settings.AI_MODEL if ai.provider.available() else None}


@router.post("/generate")
async def generate(
    body: GenerateIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    if not ai.provider.available():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "IA desativada. Ative AI_ENABLED e configure ANTHROPIC_API_KEY, ou escreva o texto manualmente.",
        )

    account = await db.get(XAccount, body.target_x_account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta destino nao encontrada")

    post = None
    if body.source_post_id:
        post = await db.get(SourcePost, body.source_post_id)
        if not post or post.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Post de origem nao encontrado")

    source_text = (post.text if post else body.source_text or "").strip()
    if not source_text:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Informe um post de origem ou um texto base."
        )

    angles, usage = await ai.provider.generate_angles(
        source_text, account.persona_prompt, body.count
    )
    db.add(
        AIGeneration(
            user_id=user.id,
            source_post_id=post.id if post else None,
            target_account_id=account.id,
            prompt=usage["prompt"],
            response=usage["raw"],
            model=usage["model"],
            tokens_input=usage["tokens_input"],
            tokens_output=usage["tokens_output"],
        )
    )
    await db.commit()
    # Angulos ainda nao viram candidates — o usuario escolhe qual salvar.
    return {"angles": angles, "model": usage["model"]}


@router.get("")
async def list_candidates(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, alias="status"),
):
    query = select(ContentCandidate).where(ContentCandidate.user_id == user.id)
    if status_filter:
        query = query.where(ContentCandidate.status == status_filter)
    rows = (
        await db.execute(query.order_by(ContentCandidate.created_at.desc()).limit(200))
    ).scalars().all()

    by_candidate = await load_media_map(db, [r.id for r in rows])
    return [_serialize(c, by_candidate.get(c.id, [])) for c in rows]


@router.post("", status_code=201)
async def create_candidate(
    body: CandidateIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    account = await db.get(XAccount, body.target_x_account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta destino nao encontrada")

    candidate = ContentCandidate(
        user_id=user.id,
        source_post_id=body.source_post_id,
        target_x_account_id=body.target_x_account_id,
        generated_text=body.text.strip(),
        origin=body.origin if body.origin in ("manual", "ai") else "manual",
        content_hash=dedup.content_hash(body.text),
    )
    db.add(candidate)
    await db.flush()
    await attach_media(db, candidate.id, body.media_ids, user.id)
    await db.commit()
    await db.refresh(candidate)
    media = await load_media_map(db, [candidate.id])
    return _serialize(candidate, media.get(candidate.id, []))


@router.post("/bulk", status_code=201)
async def create_bulk(
    body: BulkIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Distribui textos entre as contas escolhidas, anexando midia aleatoria.

    Regras que valem aqui:
      - Cada texto é usado UMA vez. Isso evita, por construcao, o mesmo conteudo
        cair em duas contas (a checagem de similaridade ainda roda na aprovacao).
      - Tudo nasce `pending`: nada vai para o X sem voce aprovar antes.
    """
    accounts = (
        await db.execute(
            select(XAccount).where(
                XAccount.id.in_(body.account_ids),
                XAccount.user_id == user.id,
                XAccount.is_active.is_(True),
            )
        )
    ).scalars().all()
    if not accounts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhuma conta valida selecionada")

    texts = (
        await db.execute(
            select(ManualSourceText).where(
                ManualSourceText.id.in_(body.text_ids), ManualSourceText.user_id == user.id
            )
        )
    ).scalars().all()
    if not texts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhum texto valido selecionado")

    media: list[MediaAsset] = []
    if body.attach_media and body.media_ids:
        media = (
            await db.execute(
                select(MediaAsset).where(
                    MediaAsset.id.in_(body.media_ids),
                    MediaAsset.user_id == user.id,
                )
            )
        ).scalars().all()
        blocked_media = [m.filename for m in media if not m.publishable]
        if blocked_media:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Midia de terceiro nao pode ser publicada: {', '.join(blocked_media)}.",
            )

    # Embaralha para a distribuicao nao seguir a ordem da tela.
    pool = list(texts)
    random.shuffle(pool)
    total = min(body.count or len(pool), len(pool))
    pool = pool[:total]

    # Round-robin embaralhado: espalha parelho entre as contas, sem viciar na primeira.
    rotation = list(accounts)
    random.shuffle(rotation)

    created: list[int] = []
    per_account: dict[str, int] = {}
    for index, text_row in enumerate(pool):
        account = rotation[index % len(rotation)]
        text = text_row.text.strip()[:280]
        if not text:
            continue

        candidate = ContentCandidate(
            user_id=user.id,
            target_x_account_id=account.id,
            generated_text=text,
            origin="manual",
            content_hash=dedup.content_hash(text),
            status="pending",
        )
        db.add(candidate)
        await db.flush()

        if media:
            chosen = random.choice(media)
            db.add(
                CandidateMedia(
                    content_candidate_id=candidate.id, media_asset_id=chosen.id, position=0
                )
            )

        text_row.used_count += 1
        created.append(candidate.id)
        per_account[account.username] = per_account.get(account.username, 0) + 1

    db.add(
        AuditLog(
            user_id=user.id,
            action="content.bulk_created",
            entity="content_candidate",
            entity_id=",".join(str(i) for i in created[:20]),
            detail={
                "count": len(created),
                "accounts": per_account,
                "media_used": len(media),
            },
        )
    )
    await db.commit()
    return {
        "created": len(created),
        "per_account": per_account,
        "skipped_texts": len(texts) - len(created),
        "ids": created,
    }


@router.patch("/{candidate_id}")
async def edit_candidate(
    candidate_id: int,
    body: CandidateUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    c = await db.get(ContentCandidate, candidate_id)
    if not c or c.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conteudo nao encontrado")
    c.generated_text = body.text.strip()
    c.content_hash = dedup.content_hash(body.text)
    if c.status == "blocked":
        c.status, c.block_reason = "pending", ""
    await db.commit()
    media = await load_media_map(db, [c.id])
    return _serialize(c, media.get(c.id, []))


@router.post("/{candidate_id}/approve")
async def approve(
    candidate_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    c = await db.get(ContentCandidate, candidate_id)
    if not c or c.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conteudo nao encontrado")

    conflict = await _check_cross_posting(db, user.id, c.generated_text, c.target_x_account_id)
    if conflict:
        c.status = "blocked"
        c.block_reason = (
            f"Conteudo {conflict['kind']} ao ja usado em @{conflict['account']} "
            f"(similaridade {conflict['similarity']}). Edite o texto para aprovar."
        )
        await db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, c.block_reason)

    c.status = "approved"
    c.approved_at = datetime.now(timezone.utc)
    c.block_reason = ""
    db.add(
        AuditLog(
            user_id=user.id,
            action="content.approved",
            entity="content_candidate",
            entity_id=str(c.id),
            detail={"account_id": c.target_x_account_id, "origin": c.origin},
        )
    )
    await db.commit()
    media = await load_media_map(db, [c.id])
    return _serialize(c, media.get(c.id, []))


@router.post("/{candidate_id}/reject")
async def reject(
    candidate_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    c = await db.get(ContentCandidate, candidate_id)
    if not c or c.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conteudo nao encontrado")
    c.status = "rejected"
    await db.commit()
    media = await load_media_map(db, [c.id])
    return _serialize(c, media.get(c.id, []))
