"""La versión desplegada (GET /api/v1/meta) y la del OpenAPI son la misma."""

import pytest
from httpx import AsyncClient

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_meta_is_public_and_matches_the_openapi(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "version": get_settings().app_version,
        "commit": get_settings().app_commit or None,
        "api": "v1",
    }
    openapi = (await client.get("/openapi.json")).json()
    assert openapi["info"]["version"] == body["version"]


@pytest.mark.asyncio
async def test_meta_reads_the_version_from_the_environment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lo que pasa la CI al construir (APP_VERSION, APP_COMMIT) es lo que responde."""
    monkeypatch.setenv("APP_VERSION", "0.3.0")
    monkeypatch.setenv("APP_COMMIT", "a1b2c3d")
    get_settings.cache_clear()
    try:
        body = (await client.get("/api/v1/meta")).json()
    finally:
        get_settings.cache_clear()
    assert (body["version"], body["commit"]) == ("0.3.0", "a1b2c3d")
