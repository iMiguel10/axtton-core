"""Autenticación y separación de actores (arquitectura §2: T1, T2, T9 y T11).

Contra el core real de SuperTokens: un doble no podría demostrar que un token
manipulado se rechaza.
"""

import base64
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import Account, sign_in

PREFIXES = ("/api/v1/workshop", "/api/v1/portal", "/api/v1/admin")
# El prefijo de cada actor; los otros dos le están vedados.
ALLOWED_PREFIX = {
    "staff": "/api/v1/workshop",
    "superadmin": "/api/v1/admin",
}

MakeAccount = Callable[[str], Awaitable[Account]]


def protected_routes() -> list[tuple[str, str]]:
    """(método, ruta) de cada operación de los tres prefijos, leídas del OpenAPI.

    Del contrato y no de una lista a mano: una ruta nueva queda cubierta sola.
    """
    from app.main import app

    routes: list[tuple[str, str]] = []
    for path, operations in app.openapi()["paths"].items():
        if path.startswith(PREFIXES):
            concrete = re.sub(r"\{[^}]+\}", str(uuid4()), path)
            routes.extend((method.upper(), concrete) for method in operations)
    return routes


def test_route_discovery_finds_every_prefix() -> None:
    """Prueba de control: si no encontrara rutas, T1 y T2 pasarían sin probar nada."""
    found = {
        prefix
        for _, path in protected_routes()
        for prefix in PREFIXES
        if path.startswith(prefix)
    }
    assert found == set(PREFIXES)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), protected_routes())
async def test_t1_every_protected_route_rejects_requests_without_session(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path)
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["staff", "superadmin"])
async def test_t2_each_actor_only_enters_its_own_prefix(
    client: AsyncClient, make_account: MakeAccount, kind: str
) -> None:
    token = await sign_in(client, await make_account(kind))
    headers = {"Authorization": f"Bearer {token}"}
    for method, path in protected_routes():
        response = await client.request(method, path, headers=headers)
        if path.startswith(ALLOWED_PREFIX[kind]):
            assert response.status_code != 403, (method, path)
        else:
            assert response.status_code == 403, (method, path)
            assert response.json() == {"code": "wrong_actor"}


@pytest.mark.asyncio
async def test_staff_session_carries_the_staff_actor(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    token = await sign_in(client, await make_account("staff"))
    response = await client.get(
        "/api/v1/workshop/me", headers={"Authorization": f"Bearer {token}"}
    )
    # Una cuenta de personal recién creada aún no trabaja en ningún taller.
    assert response.json() == {"actor": "staff", "workshops": []}


def _forge_actor(token: str, actor: str) -> str:
    """Cambia el actor dentro del token y deja la firma original."""
    header, payload, signature = token.split(".")
    padded = payload + "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    claims["actor"] = actor
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"{header}.{forged.decode()}.{signature}"


@pytest.mark.asyncio
async def test_t9_a_token_edited_by_hand_is_rejected(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    token = await sign_in(client, await make_account("staff"))
    forged = _forge_actor(token, "superadmin")
    response = await client.get(
        "/api/v1/admin/me", headers={"Authorization": f"Bearer {forged}"}
    )
    # 401 y no 403: el token ni siquiera se acepta, porque la firma no coincide.
    assert response.status_code == 401


def test_t11_only_the_session_module_writes_session_contents() -> None:
    """Ninguna otra parte del código crea sesiones ni toca su contenido."""
    forbidden = re.compile(
        r"merge_into_access_token_payload|update_access_token_payload"
        r"|create_new_session|create_new_session_without_request_response"
    )
    app_dir = Path(__file__).resolve().parent.parent / "app"
    allowed = app_dir / "core" / "sessions.py"
    offenders = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if path != allowed and forbidden.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/auth/signup", "/api/auth/public/signup"])
async def test_public_signup_is_closed_on_every_route(
    client: AsyncClient, path: str
) -> None:
    response = await client.post(
        path,
        json={
            "formFields": [
                {"id": "email", "value": f"{uuid4().hex}@example.com"},
                {"id": "password", "value": "una-contraseña-larga-1"},
            ]
        },
    )
    assert response.json() == {"status": "GENERAL_ERROR", "message": "signup_disabled"}


@pytest.mark.asyncio
async def test_a_supertokens_user_without_account_cannot_sign_in(
    client: AsyncClient, make_account: MakeAccount
) -> None:
    """Responde como una contraseña incorrecta: no revela que la cuenta existe."""
    orphan = await make_account("orphan")
    response = await client.post(
        "/api/auth/signin",
        headers={"st-auth-mode": "header"},
        json={
            "formFields": [
                {"id": "email", "value": orphan.email},
                {"id": "password", "value": orphan.password},
            ]
        },
    )
    assert response.json()["status"] == "WRONG_CREDENTIALS_ERROR"
    assert "st-access-token" not in response.headers
