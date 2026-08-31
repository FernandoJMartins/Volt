"""Fumaca da API: rotas registradas e /health — SEM banco (sem lifespan).

O ASGITransport do httpx nao executa o lifespan, entao estes testes nao
dependem de Postgres: validam apenas a montagem do app e o registro de rotas.
"""

import httpx

from app.api.accounts import router as accounts_router
from app.main import app


def test_accounts_router_surface() -> None:
    paths = {getattr(r, "path", "") for r in accounts_router.routes}
    # Metodo atual: importacao de cookies.
    assert "/api/x/accounts/browser/import-cookies" in paths
    assert "/api/x/accounts/{account_id}/browser/cookies" in paths
    # Fluxo VNC/login headed REMOVIDO — nao pode voltar sem querer.
    assert "/api/x/accounts/browser/login" not in paths
    assert "/api/x/accounts/{account_id}/browser/relogin" not in paths


async def test_health_endpoint() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
