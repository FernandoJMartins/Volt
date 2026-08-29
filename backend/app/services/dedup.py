"""Deduplicacao e bloqueio de conteudo substancialmente similar.

Duas camadas:
  1. content_hash  -> pega texto identico (normalizado).
  2. similaridade  -> pega parafrase / "substancialmente similar".

Para a similaridade o MVP usa cosseno sobre trigramas de caracteres: custo zero,
sem servico externo e sem pgvector, e eficaz em textos curtos como os do X.
Trocar por embeddings depois é so reimplementar `similarity()`.
"""

import hashlib
import math
import re
import unicodedata
from collections import Counter

_WS = re.compile(r"\s+")
_URL = re.compile(r"https?://\S+")
_NOISE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = _URL.sub(" ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _NOISE.sub(" ", text)
    return _WS.sub(" ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def _trigrams(text: str) -> Counter:
    norm = normalize(text)
    if len(norm) < 3:
        return Counter([norm] if norm else [])
    return Counter(norm[i : i + 3] for i in range(len(norm) - 2))


def similarity(a: str, b: str) -> float:
    """Cosseno entre os vetores de trigramas. 0.0 = nada a ver, 1.0 = identico."""
    va, vb = _trigrams(a), _trigrams(b)
    if not va or not vb:
        return 0.0
    common = set(va) & set(vb)
    if not common:
        return 0.0
    dot = sum(va[t] * vb[t] for t in common)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def find_conflict(text: str, existing: list[tuple[int, str, str]], threshold: float) -> dict | None:
    """`existing` = [(id, texto, rotulo_da_conta)]. Retorna o primeiro conflito acima do limiar."""
    new_hash = content_hash(text)
    for other_id, other_text, label in existing:
        if content_hash(other_text) == new_hash:
            return {"id": other_id, "account": label, "similarity": 1.0, "kind": "identico"}
        sim = similarity(text, other_text)
        if sim >= threshold:
            return {"id": other_id, "account": label, "similarity": round(sim, 3), "kind": "similar"}
    return None
