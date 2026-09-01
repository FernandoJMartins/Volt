"""Reescrita rapida SEM IA: sinonimos + variacao leve de frase, instantaneo.

Existe para o piloto automatico (XAccount.content_mode="fast") e como fallback
quando a IA local demora demais (ver AUTOPILOT_AI_TIMEOUT_SECONDS). Qualidade
e' bem mais mecanica que a IA — troca palavras por sinonimos de um dicionario
fixo e varia conectores — mas roda em microssegundos, sem depender do Ollama.
"""

import random
import re

# Dicionario PT-BR pequeno e generico de proposito: troca palavras comuns sem
# arriscar mudar o sentido do post. Nao tenta ser um paraphraser completo.
_SYNONYMS: dict[str, list[str]] = {
    "muito": ["bastante", "demais", "pra caramba"],
    "hoje": ["hoje mesmo", "agora", "neste exato momento"],
    "quero": ["tô querendo", "tô a fim de", "bateu vontade de"],
    "gosto": ["curto", "adoro", "sou fã de"],
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
}

_CONNECTOR_SWAPS = [
    ("e ", ["e ", "e também ", "além disso, "]),
    ("mas ", ["mas ", "só que ", "porém "]),
    ("porque ", ["porque ", "já que ", "pois "]),
]

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _swap_word(match: re.Match) -> str:
    word = match.group(0)
    key = word.lower()
    options = _SYNONYMS.get(key)
    if not options or random.random() > 0.6:  # nem toda ocorrencia troca — fica menos mecanico
        return word
    chosen = random.choice(options)
    if word[:1].isupper():
        chosen = chosen[:1].upper() + chosen[1:]
    return chosen


def reword(text: str, limit: int = 280) -> str:
    """Troca sinonimos conhecidos e varia conectores. Sem match, devolve o texto original."""
    out = _WORD_RE.sub(_swap_word, text)
    for needle, options in _CONNECTOR_SWAPS:
        if needle in out.lower():
            out = re.sub(re.escape(needle), random.choice(options), out, count=1, flags=re.IGNORECASE)
    return out.strip()[:limit]
