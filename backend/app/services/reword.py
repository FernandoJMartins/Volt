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
    """Troca sinonimos e conectores conhecidos, palavra inteira. Sem match, devolve
    o texto original (so' aparado no limite)."""
    return _WORD_RE.sub(_swap_word, text).strip()[:limit]
