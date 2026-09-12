"""Troca automatica de links do Telegram pelo link proprio cadastrado na conta.

Contas clonam posts de fontes que divulgam grupo/canal/bot do Telegram — sem
essa troca, o post reescrito levaria trafego pro Telegram de outra pessoa em
vez do link de conversao da propria conta (ex: pagina no Spectrum Red).

Aplicado centralmente em cada ponto que gera o texto final de um
ContentCandidate (IA, reescrita rapida ou texto manual/colado) — ver
app/services/autopilot.py e app/api/content.py.
"""

import re

# Protocolo e "www." opcionais; aceita qualquer subdominio (ex: sub.t.me) e
# domina case-insensitive. `_BREAK` cobre os pontos onde o scraping do X
# quebra o link em linhas — depois do protocolo ("http://\nt.me/..."), entre
# o dominio e a barra ("t.me\n/bot") e, visto em producao, DENTRO do proprio
# path/nome do bot partido ao meio ("Telegram.me/clubdoscorninh\noscorninhos_bot").
# `_BREAK` exige uma quebra de linha de verdade (nao so' um espaco) pra nao
# confundir isso com uma palavra real separada por espaco depois do link (ex:
# "t.me/exemplo agora" nao pode virar "REDIRECT" comendo o "agora"). O path e'
# limitado a 2 pedacos partidos (o caso real de producao) pra minimizar o
# risco de engolir uma palavra legitima caso o link caia justo no fim de uma
# linha seguida de mais texto na proxima.
_BREAK = r"[ \t]*\n\s*"
_TELEGRAM_RE = re.compile(
    rf"(?:https?://(?:{_BREAK})?)?(?:www\.)?(?:[a-z0-9-]+\.)*(?:t\.me|telegram\.me|telegram\.dog)"
    rf"(?:(?:{_BREAK})?/(?:[\w-]+(?:{_BREAK})?){{1,2}})?",
    re.IGNORECASE,
)


def replace_telegram_links(text: str, redirect_url: str) -> str:
    """Troca qualquer link do Telegram (t.me, telegram.me, telegram.dog — com
    ou sem protocolo/www, qualquer subdominio) pelo `redirect_url` da conta.

    Sem `redirect_url` configurado na conta, devolve o texto sem mudanca
    (nada pra trocar — feature opt-in por conta)."""
    if not redirect_url or not text:
        return text
    return _TELEGRAM_RE.sub(redirect_url, text)
