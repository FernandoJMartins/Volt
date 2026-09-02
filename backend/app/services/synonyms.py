"""Busca de sinonimos PT-BR num site publico gratuito (sem API oficial disponivel).

Nao existe uma REST API estavel e gratuita de sinonimos em PT-BR (as opcoes
conhecidas — ex: synonymous-ptBR-api no Heroku — estao fora do ar). A alternativa
viavel e' scraping leve do sinonimos.com.br: pagina por palavra, sinonimos como
links `<a href="/palavra/">` dentro do primeiro bloco de sentido.

Por ser scraping de site de terceiros (frágil a mudanca de layout, pode cair a
qualquer momento), isto e' estritamente best-effort: qualquer falha devolve uma
lista vazia, nunca propaga excecao. Quem chama (reword.py) sempre tem o
dicionario local como fallback.
"""

import logging
import re
import unicodedata

import httpx

from app.config import settings

log = logging.getLogger(__name__)

BASE = "https://www.sinonimos.com.br"

# So' o PRIMEIRO bloco de sentido (`syn-list-1`) — a pagina lista varios sentidos
# da palavra e so' o primeiro costuma ser o uso mais comum/relevante. Sem isso,
# um regex generico de `<a href="/x/">` tambem pega links da nav lateral do site
# (menu "Escrever", rodape etc) e gera lixo (ex: slugs tipo "por-esse-motivo").
_BLOCK_RE = re.compile(r'class="syn-list[^"]*syn-list-1[^"]*">(.*?)</p>', re.DOTALL)
# Dentro do bloco, so' os links marcados como sinonimo de fato (`class="sinonimo"`).
# Captura o TEXTO do link (acentuado, ex: "frenético"), nao o slug do href (que o
# site sempre grava sem acento, ex: "/frenetico/") — o texto e' o que entra natural
# no post reescrito.
_LINK_RE = re.compile(r'<a href="/[^"]+/" class="sinonimo">([^<]+)</a>')

_cache: dict[str, list[str]] = {}


def _slug(word: str) -> str:
    """O site usa a palavra SEM acento na URL (ex: /rapido/ pra "rápido"), mesmo
    que o texto exibido nos links venha acentuado. Sem isso, palavra acentuada
    (comum em PT-BR: "rápido", "não", "café"...) cai numa URL que nao existe."""
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


async def lookup(word: str) -> list[str]:
    """Sinonimos de `word`, ou [] se nao achou / a busca falhou por qualquer motivo."""
    key = word.lower()
    if key in _cache:
        return _cache[key]

    result: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=settings.SYNONYM_API_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{BASE}/{_slug(key)}/", follow_redirects=True)
        if resp.status_code == 200:
            block = _BLOCK_RE.search(resp.text)
            if block:
                found = _LINK_RE.findall(block.group(1))
                # Remove a propria palavra e duplicatas, preserva ordem.
                seen = {key}
                for candidate in found:
                    candidate_key = candidate.strip().lower()
                    if candidate_key and candidate_key not in seen:
                        seen.add(candidate_key)
                        result.append(candidate.strip())
    except Exception as exc:  # noqa: BLE001 — scraping best-effort, nunca derruba a reescrita
        log.debug("synonyms.lookup falhou pra '%s': %s", word, exc)
        result = []

    _cache[key] = result
    return result
