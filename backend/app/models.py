from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class XAccount(Base):
    """Conta do X conectada via OAuth. Tokens sempre criptografados."""

    __tablename__ = "x_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    x_user_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    avatar_url: Mapped[str] = mapped_column(String(512), default="")

    # --- Autenticacao via API oficial (legado, mantido intacto) ---
    access_token_encrypted: Mapped[str] = mapped_column(Text, default="")
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    # --- Autenticacao via navegador (Playwright) ---
    # "browser" (storage_state do Playwright) ou "oauth" (API oficial).
    auth_method: Mapped[str] = mapped_column(String(16), default="browser")
    # storage_state do Playwright (cookies + localStorage) criptografado em repouso.
    # Equivale a uma credencial: nunca sai do banco em texto puro, nunca vai pro Git.
    session_state_encrypted: Mapped[str] = mapped_column(Text, default="")
    session_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    session_updated_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    # UA fixo por conta: mantem a "impressao digital" estavel entre sessoes.
    user_agent: Mapped[str] = mapped_column(String(512), default="")

    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Identidade propria da conta (evita que virem copias umas das outras)
    persona_prompt: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[list] = mapped_column(JSON, default=list)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    # Janela de publicacao
    posts_per_day: Mapped[int] = mapped_column(Integer, default=8)
    window_start: Mapped[str] = mapped_column(String(5), default="08:00")
    window_end: Mapped[str] = mapped_column(String(5), default="23:00")
    min_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)

    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "x_user_id", name="uq_user_xaccount"),)


class MonitoredAccount(Base):
    """Fonte monitorada. source_type define de onde os posts vem."""

    __tablename__ = "monitored_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    x_user_id: Mapped[str] = mapped_column(String(64), default="")
    username: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    source_type: Mapped[str] = mapped_column(String(16), default="web")  # web | x_api | manual
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_collected_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    last_seen_post_id: Mapped[str] = mapped_column(String(64), default="")
    # Media movel de engajamento — base do score relativo
    engagement_baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ManualSourceText(Base):
    """Pool de textos do proprio usuario. Fonte custo-zero do MVP."""

    __tablename__ = "manual_source_texts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class SourcePost(Base):
    """Post coletado. x_post_id UNIQUE impede processamento duplicado."""

    __tablename__ = "source_posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    x_post_id: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    monitored_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitored_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    text: Mapped[str] = mapped_column(Text)
    author_username: Mapped[str] = mapped_column(String(64), default="")
    posted_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    likes: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)

    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    media_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    original_url: Mapped[str] = mapped_column(String(512), default="")

    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)

    collected_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ContentCandidate(Base):
    """Conteudo pronto (gerado por IA ou escrito a mao) para uma conta destino."""

    __tablename__ = "content_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_posts.id", ondelete="SET NULL"), nullable=True
    )
    target_x_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("x_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )

    generated_text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), default="manual")  # manual | ai
    media_reference: Mapped[dict] = mapped_column(JSON, default=dict)

    # pending | approved | scheduled | published | rejected | failed | blocked
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    block_reason: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    account = relationship("XAccount", lazy="joined")


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    x_account_id: Mapped[int] = mapped_column(ForeignKey("x_accounts.id", ondelete="CASCADE"), index=True)
    content_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("content_candidates.id", ondelete="CASCADE")
    )
    scheduled_at: Mapped[datetime] = mapped_column(TS, index=True)
    # queued | publishing | published | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    published_post_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    candidate = relationship("ContentCandidate", lazy="joined")
    account = relationship("XAccount", lazy="joined")


class RetweetJob(Base):
    """Retweet escalonado entre as contas do proprio usuario."""

    __tablename__ = "retweet_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_tweet_id: Mapped[str] = mapped_column(String(64))
    origin_x_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("x_accounts.id", ondelete="SET NULL"), nullable=True
    )
    target_x_account_id: Mapped[int] = mapped_column(
        ForeignKey("x_accounts.id", ondelete="CASCADE"), index=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(TS, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    retweet_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    target = relationship("XAccount", foreign_keys=[target_x_account_id], lazy="joined")


class MediaAsset(Base):
    """Midia do usuario. `origin` separa midia PROPRIA de midia de terceiro.

    Midia de terceiro entra como 'source_reference' e NAO pode ser publicada —
    republicar midia alheia é risco juridico. So 'owned' e 'licensed' publicam.
    """

    __tablename__ = "media_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="image")  # image | video | gif
    # owned | licensed | source_reference
    origin: Mapped[str] = mapped_column(String(20), default="owned")
    usage_rights: Mapped[str] = mapped_column(Text, default="")
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    PUBLISHABLE = ("owned", "licensed")

    @property
    def publishable(self) -> bool:
        return self.origin in self.PUBLISHABLE


class CandidateMedia(Base):
    """Liga conteudo <-> midia, preservando a ordem em que aparecem no post."""

    __tablename__ = "candidate_media"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("content_candidates.id", ondelete="CASCADE"), index=True
    )
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)

    asset = relationship("MediaAsset", lazy="joined")


class AIGeneration(Base):
    __tablename__ = "ai_generations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_posts.id", ondelete="SET NULL"), nullable=True
    )
    target_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("x_accounts.id", ondelete="SET NULL"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64), default="")
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
