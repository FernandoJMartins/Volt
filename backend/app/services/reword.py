"""Reescrita rapida SEM IA: sinonimos + case invertido, quase instantaneo.

Modo PRINCIPAL do piloto automatico (Account.content_mode="fast", default pra
contas novas) e fallback quando a IA local demora demais (ver
AUTOPILOT_AI_TIMEOUT_SECONDS). Dois mecanismos, combinados:

  1. Troca de sinonimos: dicionario local fixo primeiro; pra palavras fora dele,
     busca best-effort no app.services.synonyms (scraping de site publico —
     nunca bloqueia nem quebra a reescrita se falhar/demorar). Termos +18 NUNCA
     sao mandados pra busca externa — ficam de fora do split, voltam inalterados
     na concatenacao final.
  2. Case invertido: o texto final inteiro vira UPPERCASE ou lowercase — o
     OPOSTO do case predominante do texto original. Evita's paridade textual
     "no olho" entre o post original e a reescrita. URLs ficam de fora do flip
     (mudar case de path pode quebrar link case-sensitive).
"""

import asyncio
import random
import re

from app.config import settings
from app.services import synonyms

# Dicionario PT-BR pequeno e generico de proposito: troca palavras comuns sem
# arriscar mudar o sentido do post. Nao tenta ser um paraphraser completo.
_SYNONYMS: dict[str, list[str]] = {
    "muito": ["bastante", "demais", "pra caramba"],
    "hoje": ["hoje mesmo", "agora", "neste exato momento"],
    "quero": ["tô querendo", "tô a fim de", "bateu vontade de"],
    # Sem opcoes com preposicao propria (ex: "sou fa de") — "gosto de X" no
    # original ja tem o "de" depois; juntar os dois duplica ("sou fa de de X").
    "gosto": ["curto", "adoro"],
    "sempre": ["toda vez", "sem falta", "invariavelmente"],
    "agora": ["nesse instante", "já já", "de cara"],
    "legal": ["massa", "top", "show"],
    "amiga": ["parceira", "cúmplice", "confidente"],
    "amigo": ["parceiro", "cúmplice", "confidente"],
    "vontade": ["tesão", "vontade danada", "desejo"],
    "noite": ["madrugada", "noitada", "night"],
    "corpo": ["shape", "corpinho", "forma"],
    "ciúme": ["ciuminho", "ciúme besta", "possessividade"],
    "sozinha": ["desacompanhada", "sem companhia", "por conta própria"],
    "sozinho": ["desacompanhado", "sem companhia", "por conta própria"],
    # Conectores: entram no mesmo dicionario pra reusar o casamento por
    # PALAVRA INTEIRA de _WORD_RE (\w+) — trocar por substring crua (regex
    # direta em "e ") pegava pedacos de outras palavras (ex: "hoje" virava
    # "hojalém disso"). Palavra inteira elimina essa classe de bug.
    "e": ["e", "e também", "e ainda"],
    "mas": ["mas", "só que", "porém"],
    "porque": ["porque", "já que", "pois"],
}

# Termos +18 comuns: nunca sao mandados pra busca de sinonimos externa (site de
# terceiros) — ficam de fora do split e voltam inalterados na concatenacao.
# Lista pequena e de proposito, nao exaustiva (mesmo espirito do _SYNONYMS acima).
_ADULT_TERMS: frozenset[str] = frozenset(
    {
        "sexo",
        "gozar",
        "gozada",
        "pau",
        "pica",
        "buceta",
        "xoxota",
        "boquete",
        "peito",
        "peitos",
        "seios",
        "bunda",
        "cu",
        "trepar",
        "transar",
        "tesão",
        "tesao",
        "safada",
        "safado",
        "putaria",
        "nude",
        "nudes",
        "pelada",
        "pelado",
        "gostosa",
        "gostoso",
    }
)

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+")
_MIN_EXTERNAL_LEN = 4  # abaixo disso nao vale o custo do lookup externo


def _is_mostly_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper > len(letters) / 2


async def _resolve_replacements(text: str) -> dict[str, str]:
    """Mapa {palavra_minuscula: substituta}, dicionario local + busca externa."""
    replacements: dict[str, str] = {}
    to_lookup: list[str] = []

    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        key = word.lower()
        if not word.isalpha() or key in replacements or key in to_lookup:
            continue
        if random.random() > 0.6:  # nem toda palavra troca — fica menos mecanico
            continue
        if key in _SYNONYMS:
            replacements[key] = random.choice(_SYNONYMS[key])
            continue
        if key in _ADULT_TERMS or len(key) < _MIN_EXTERNAL_LEN:
            continue  # termo +18 ou palavra curta demais: nao vale a busca externa
        if len(to_lookup) < settings.SYNONYM_API_MAX_LOOKUPS:
            to_lookup.append(key)

    if to_lookup:
        results = await asyncio.gather(*(synonyms.lookup(w) for w in to_lookup))
        for word, options in zip(to_lookup, results):
            if options:
                replacements[word] = random.choice(options)

    return replacements


def _apply_replacements(text: str, replacements: dict[str, str]) -> str:
    def _swap(match: re.Match) -> str:
        return replacements.get(match.group(0).lower(), match.group(0))

    return _WORD_RE.sub(_swap, text)


def _flip_case(text: str, upper: bool) -> str:
    """upper()/lower() no texto inteiro, preservando URLs (case pode importar
    pro path de um link, ex: ID de video)."""
    parts = _URL_RE.split(text)
    urls = _URL_RE.findall(text)
    out: list[str] = []
    for i, part in enumerate(parts):
        out.append(part.upper() if upper else part.lower())
        if i < len(urls):
            out.append(urls[i])
    return "".join(out)


async def reword(text: str, limit: int = 280) -> str:
    """Troca sinonimos conhecidos e joga o resultado pro case OPOSTO do original
    (maiuscula predominante -> minuscula, e vice-versa). Sem nenhum sinonimo
    encontrado, ainda assim aplica o flip de case."""
    replacements = await _resolve_replacements(text)
    swapped = _apply_replacements(text, replacements)
    flipped = _flip_case(swapped, upper=not _is_mostly_upper(text))
    return flipped.strip()[:limit]
