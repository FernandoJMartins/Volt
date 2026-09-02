"""Resolve qual page-driver (x_web ou threads_web) usar pra uma conta,
dado `account.platform`. Os dois modulos tem o mesmo contrato: is_logged_in,
resolve_identity, fetch_timeline, publish, post_url, BASE — ver x_web.py e
threads_web.py.
"""

from types import ModuleType

from app.services import threads_web, x_web

_DRIVERS: dict[str, ModuleType] = {
    "x": x_web,
    "threads": threads_web,
}


def driver_for(platform: str) -> ModuleType:
    driver = _DRIVERS.get(platform)
    if driver is None:
        raise ValueError(f"plataforma desconhecida: {platform!r}")
    return driver
