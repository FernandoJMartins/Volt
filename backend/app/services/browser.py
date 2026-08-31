"""Camada de navegador com ISOLAMENTO ESTRITO por conta.

Regra inegociavel deste modulo:

    Uma conta -> um BrowserContext proprio, criado do zero e fechado ao fim.
    Duas contas NUNCA compartilham contexto, cookies, localStorage ou processo.

Como a garantia e' obtida
-------------------------
1. Cada operacao abre um `BrowserContext` novo, semeado APENAS com o
   storage_state daquela conta (descriptografado na hora). Contexto do
   Playwright e' uma particao de armazenamento isolada — cookies de A jamais
   aparecem num contexto de B.
2. O blob salvo carrega o `account_id`. Ao carregar, conferimos que o estado
   pertence a` conta pedida (`_load_state`); qualquer troca acidental no banco
   ou na criptografia vira erro em vez de vazamento silencioso.
3. Um lock por conta impede que dois jobs dirijam a MESMA conta ao mesmo tempo
   (o que corromperia o storage_state ao salvar). Contas diferentes rodam em
   paralelo, cada uma no seu contexto.
4. O contexto e' sempre fechado no `finally`. Nada de contexto reaproveitado
   entre contas — a unica coisa compartilhada e' o processo do Chromium no modo
   "context" (particoes ja sao isoladas); no modo "process" nem isso.

Nada aqui tenta mascarar automacao. O isolamento existe para estabilidade,
seguranca de sessao e para nao misturar identidades — nao para evadir deteccao.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.config import settings
from app.core.security import decrypt, encrypt

log = logging.getLogger("browser")

# UA padrao usado quando a conta ainda nao tem um fixado. Chromium estavel recente.
_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class SessionExpired(Exception):
    """A sessao salva nao esta mais autenticada. Precisa de novo login headed."""


class SessionMismatch(Exception):
    """O storage_state carregado nao pertence a` conta pedida. Aborta na hora."""


def wrap_state(account_id: int, state: dict) -> str:
    """Empacota o storage_state com o dono e criptografa para repouso."""
    blob = {
        "account_id": account_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
    }
    return encrypt(json.dumps(blob))


def _load_state(account_id: int, encrypted: str) -> dict | None:
    """Descriptografa e valida a posse. Retorna o storage_state ou None se vazio."""
    if not encrypted:
        return None
    raw = decrypt(encrypted)
    if not raw:
        log.warning("Conta %s: storage_state ilegivel (chave trocada?).", account_id)
        return None
    blob = json.loads(raw)
    if blob.get("account_id") != account_id:
        # Trava de seguranca: estado de outra conta jamais entra neste contexto.
        raise SessionMismatch(
            f"storage_state pertence a` conta {blob.get('account_id')}, "
            f"nao a` {account_id}. Operacao abortada."
        )
    return blob.get("state")


class BrowserManager:
    """Singleton por processo. Guarda o Playwright, o Browser compartilhado e os
    locks por conta. Cada `session()` cria e destroi seu proprio contexto."""

    def __init__(self) -> None:
        self._pw = None
        self._browser: Browser | None = None
        self._start_lock = asyncio.Lock()
        self._account_locks: dict[int, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _ensure_browser(self) -> Browser:
        if self._browser and self._browser.is_connected():
            return self._browser
        async with self._start_lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            if self._pw is None:
                self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=settings.BROWSER_HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            log.info("Chromium iniciado (headless=%s)", settings.BROWSER_HEADLESS)
            return self._browser

    async def _lock_for(self, account_id: int) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._account_locks.get(account_id)
            if lock is None:
                lock = asyncio.Lock()
                self._account_locks[account_id] = lock
            return lock

    @asynccontextmanager
    async def session(self, account):
        """Contexto isolado para UMA conta (sempre headless — sem login manual).

        Uso:
            async with manager.session(account) as (page, ctx):
                ...  # dirige a pagina
            # ao sair: storage_state salvo criptografado + contexto fechado

        `account` precisa expor: id, session_state_encrypted, user_agent.
        O storage_state atualizado e' devolvido em `account.session_state_encrypted`
        para o chamador persistir no banco.
        """
        lock = await self._lock_for(account.id)
        async with lock:  # serializa a MESMA conta; contas distintas nao se bloqueiam
            state = _load_state(account.id, account.session_state_encrypted or "")

            own_browser: Browser | None = None
            process_mode = settings.BROWSER_ISOLATION == "process"

            if process_mode:
                # Modo 'process' exige um Browser dedicado por conta (isolamento maximo).
                if self._pw is None:
                    self._pw = await async_playwright().start()
                own_browser = await self._pw.chromium.launch(
                    headless=settings.BROWSER_HEADLESS,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                browser = own_browser
            else:
                browser = await self._ensure_browser()

            context: BrowserContext = await browser.new_context(
                storage_state=state,  # SO' o estado desta conta entra aqui
                user_agent=account.user_agent or _DEFAULT_UA,
                locale=settings.BROWSER_LOCALE,
                viewport={"width": 1280, "height": 900},
            )
            page: Page = await context.new_page()
            try:
                yield page, context
                # Persiste o estado atualizado (cookies renovados etc.) desta conta.
                fresh = await context.storage_state()
                account.session_state_encrypted = wrap_state(account.id, fresh)
                account.session_updated_at = datetime.now(timezone.utc)
            finally:
                await context.close()
                if own_browser is not None:
                    await own_browser.close()

    async def shutdown(self) -> None:
        if self._browser and self._browser.is_connected():
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = None
        self._pw = None


# Singleton por processo (API, worker e scheduler cada um tem o seu).
manager = BrowserManager()
