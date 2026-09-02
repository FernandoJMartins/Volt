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
# domina case-insensitive. `\s*` depois do protocolo cobre o caso comum de
# scraping onde o X quebra o link em linhas ("http://\nt.me/..."). O path
# (`/\S*`) para no primeiro espaco/quebra de linha.
_TELEGRAM_RE = re.compile(
    r"(?:https?://\s*)?(?:www\.)?(?:[a-z0-9-]+\.)*(?:t\.me|telegram\.me|telegram\.dog)(?:/\S*)?",
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
