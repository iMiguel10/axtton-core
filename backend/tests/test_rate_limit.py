"""Límite de peticiones (RNF-06): inicio de sesión, recuperación de contraseña,
invitaciones y cambio de contraseña. Y que no se pueda esquivar cambiando la URL
ni inventándose una IP.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.client_ip import client_ip, parse_trusted_proxies
from app.core.config import Settings
from app.infra.rate_limit import (
    DisabledRateLimiter,
    LimitsRateLimiter,
    build_rate_limiter,
    current_rate_limiter,
    set_rate_limiter,
    storage_uri,
)
from tests.conftest import Account, sign_in


@pytest_asyncio.fixture(autouse=True)
async def limiter() -> AsyncIterator[None]:
    """Un limitador real con almacén en memoria, nuevo en cada prueba."""
    previous = current_rate_limiter()
    set_rate_limiter(LimitsRateLimiter("async+memory://"))
    yield
    set_rate_limiter(previous)


def signin_body(email: str, password: str = "no-es-la-contraseña") -> dict:
    return {
        "formFields": [
            {"id": "email", "value": email},
            {"id": "password", "value": password},
        ]
    }


@pytest.mark.asyncio
async def test_signin_is_limited_per_email(client: AsyncClient) -> None:
    email = f"alguien-{uuid4().hex[:8]}@example.com"
    for _ in range(10):
        response = await client.post("/api/auth/signin", json=signin_body(email))
        assert response.json()["status"] == "WRONG_CREDENTIALS_ERROR"

    response = await client.post("/api/auth/signin", json=signin_body(email))
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0

    # Es por email: otra cuenta sigue pudiendo intentarlo.
    other = await client.post("/api/auth/signin", json=signin_body("otra@example.com"))
    assert other.status_code == 200


@pytest.mark.asyncio
async def test_the_limit_ignores_the_case_of_the_email(client: AsyncClient) -> None:
    email = f"alguien-{uuid4().hex[:8]}@example.com"
    for _ in range(10):
        await client.post("/api/auth/signin", json=signin_body(email))
    response = await client.post("/api/auth/signin", json=signin_body(email.upper()))
    assert response.status_code == 429


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/signin/",
        "/api/auth/public/signin",
        "/api/auth/signin;x",
        "/API/Auth//SignIn",
    ],
)
@pytest.mark.asyncio
async def test_another_spelling_of_the_url_does_not_skip_the_limit(
    client: AsyncClient, path: str
) -> None:
    email = f"alguien-{uuid4().hex[:8]}@example.com"
    for _ in range(10):
        await client.post("/api/auth/signin", json=signin_body(email))
    response = await client.post(path, json=signin_body(email))
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_signin_is_limited_per_ip(client: AsyncClient) -> None:
    """Emails distintos desde la misma IP: frena a quien prueba muchas cuentas."""
    for _ in range(30):
        email = f"alguien-{uuid4().hex[:8]}@example.com"
        await client.post("/api/auth/signin", json=signin_body(email))
    response = await client.post("/api/auth/signin", json=signin_body("x@example.com"))
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_a_forged_forwarded_for_does_not_skip_the_ip_limit(
    client: AsyncClient,
) -> None:
    """Sin proxies de confianza configurados, X-Forwarded-For se ignora."""
    for i in range(30):
        await client.post(
            "/api/auth/signin",
            json=signin_body(f"alguien-{uuid4().hex[:8]}@example.com"),
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        )
    response = await client.post(
        "/api/auth/signin",
        json=signin_body("x@example.com"),
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_the_body_still_reaches_supertokens(
    client: AsyncClient, make_account: Callable[[str], Awaitable[Account]]
) -> None:
    """El middleware lee el cuerpo para sacar el email: SuperTokens tiene que
    seguir recibiéndolo entero, o ningún inicio de sesión funcionaría."""
    account = await make_account("staff")
    assert await sign_in(client, account)


@pytest.mark.asyncio
async def test_password_reset_is_limited_per_email(client: AsyncClient) -> None:
    body = {"formFields": [{"id": "email", "value": "quien@example.com"}]}
    for _ in range(3):
        response = await client.post("/api/auth/user/password/reset/token", json=body)
        assert response.json()["status"] == "OK"
    response = await client.post("/api/auth/user/password/reset/token", json=body)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_accepting_an_invitation_is_limited_per_link(
    client: AsyncClient,
) -> None:
    """Aceptar con un email que ya tiene cuenta exige su contraseña: sin límite,
    un enlace serviría para probar contraseñas sin frenos."""
    path = f"/api/v1/invitations/{uuid4()}/{uuid4().hex}/accept"
    body = {"password": "una-contraseña-larga-1"}
    for _ in range(5):
        response = await client.post(path, json=body)
        assert response.status_code == 404
    response = await client.post(path, json=body)
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_changing_the_password_is_limited_per_user(
    client: AsyncClient, make_account: Callable[[str], Awaitable[Account]]
) -> None:
    account = await make_account("staff")
    token = await sign_in(client, account)
    headers = {"Authorization": f"Bearer {token}"}
    wrong = {"current_password": "no-es-esta", "new_password": "otra-contraseña-larga"}
    for _ in range(5):
        response = await client.post(
            "/api/v1/workshop/account/password", json=wrong, headers=headers
        )
        assert response.status_code == 403
    # Ni con la contraseña correcta: el límite va antes de comprobarla.
    right = {"current_password": account.password, "new_password": "otra-larga-123"}
    response = await client.post(
        "/api/v1/workshop/account/password", json=right, headers=headers
    )
    assert response.status_code == 429


# --- Piezas sueltas -----------------------------------------------------------


def test_forwarded_for_only_counts_behind_a_trusted_proxy() -> None:
    trusted = parse_trusted_proxies("10.0.0.0/8")
    # La conexión no viene de un proxy propio: la cabecera la ha escrito el cliente.
    assert client_ip("203.0.113.5", "1.2.3.4", trusted) == "203.0.113.5"
    # Viene del proxy: la primera IP no fiable por la derecha. Lo de la izquierda
    # ("1.2.3.4") lo pudo escribir el cliente.
    assert client_ip("10.0.0.2", "1.2.3.4, 198.51.100.9", trusted) == "198.51.100.9"
    assert client_ip("10.0.0.2", "198.51.100.9, 10.0.0.3", trusted) == "198.51.100.9"


def test_valkey_url_becomes_the_async_storage() -> None:
    assert storage_uri("redis://valkey:6379/0") == "async+valkey://valkey:6379/0"
    assert storage_uri("rediss://host:6380/1") == "async+valkeys://host:6380/1"


def test_without_valkey_nothing_is_limited() -> None:
    settings = Settings(rate_limit_enabled=True, valkey_url=None)  # type: ignore[call-arg]
    assert isinstance(build_rate_limiter(settings), DisabledRateLimiter)


@pytest.mark.asyncio
async def test_if_the_store_is_down_requests_pass() -> None:
    """Mejor un rato sin límite que nadie pueda entrar (y sin pagar el timeout en
    cada petición mientras está caído)."""
    now = [0.0]
    limiter = LimitsRateLimiter("async+valkey://no-existe:6379", clock=lambda: now[0])
    assert (await limiter.hit("1/hour", "x")).allowed
    assert (await limiter.hit("1/hour", "x")).allowed


@pytest.mark.skipif("VALKEY_URL" not in os.environ, reason="sin Valkey")
@pytest.mark.asyncio
async def test_the_real_valkey_counts() -> None:
    limiter = LimitsRateLimiter(storage_uri(os.environ["VALKEY_URL"]))
    key = uuid4().hex
    assert (await limiter.hit("2/minute", "test", key)).allowed
    assert (await limiter.hit("2/minute", "test", key)).allowed
    result = await limiter.hit("2/minute", "test", key)
    assert not result.allowed
    assert result.retry_after > 0


# --- Formas de esquivar el límite que no tenían prueba ------------------------


@pytest.mark.asyncio
async def test_spaces_around_the_email_do_not_skip_the_limit(
    client: AsyncClient,
) -> None:
    """SuperTokens recorta el email antes de comprobarlo: si el límite no lo
    hiciera, " ana@x " y "ana@x" serían dos contadores para la misma cuenta."""
    email = f"alguien-{uuid4().hex[:8]}@example.com"
    for _ in range(10):
        await client.post("/api/auth/signin", json=signin_body(email))
    response = await client.post("/api/auth/signin", json=signin_body(f"  {email} "))
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_password_reset_is_limited_per_ip_across_emails(
    client: AsyncClient,
) -> None:
    for _ in range(10):
        body = {"formFields": [{"id": "email", "value": f"{uuid4().hex}@example.com"}]}
        response = await client.post("/api/auth/user/password/reset/token", json=body)
        assert response.status_code == 200
    body = {"formFields": [{"id": "email", "value": "otro@example.com"}]}
    response = await client.post("/api/auth/user/password/reset/token", json=body)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_changing_the_workshop_in_an_invitation_link_does_not_reset_its_limit(
    client: AsyncClient,
) -> None:
    """El límite por enlace va por el token, no por la URL entera: cambiar el
    taller del enlace no da cinco intentos más con el mismo token."""
    token = uuid4().hex
    body = {"password": "una-contraseña-larga-1"}
    for _ in range(5):
        await client.post(f"/api/v1/invitations/{uuid4()}/{token}/accept", json=body)
    response = await client.post(
        f"/api/v1/invitations/{uuid4()}/{token}/accept", json=body
    )
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_accepting_a_superadmin_invitation_is_limited_per_link(
    client: AsyncClient,
) -> None:
    """Igual que la de empleado (RF-110): con un email que ya tiene cuenta, aceptar
    exige su contraseña, así que sin límite serviría para probarlas."""
    path = f"/api/v1/superadmin-invitations/{uuid4().hex}/accept"
    body = {"password": "una-contraseña-larga-1"}
    for _ in range(5):
        response = await client.post(path, json=body)
        assert response.status_code == 404
    response = await client.post(path, json=body)
    assert response.status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/invitations/{workshop}/{token}",
        "/api/v1/superadmin-invitations/{token}",
    ],
)
async def test_viewing_invitations_is_limited_per_ip(
    client: AsyncClient, path: str
) -> None:
    for _ in range(60):
        url = path.format(workshop=uuid4(), token=uuid4().hex)
        assert (await client.get(url)).status_code == 404
    url = path.format(workshop=uuid4(), token=uuid4().hex)
    assert (await client.get(url)).status_code == 429


@pytest.mark.asyncio
async def test_a_superadmin_changing_the_password_is_limited_too(
    client: AsyncClient, make_account: Callable[[str], Awaitable[Account]]
) -> None:
    """La misma operación cuelga de /workshop y de /admin: el límite vale en las dos."""
    account = await make_account("superadmin")
    headers = {"Authorization": f"Bearer {await sign_in(client, account)}"}
    wrong = {"current_password": "no-es-esta", "new_password": "otra-contraseña-larga"}
    for _ in range(5):
        response = await client.post(
            "/api/v1/admin/account/password", json=wrong, headers=headers
        )
        assert response.status_code == 403
    response = await client.post(
        "/api/v1/admin/account/password", json=wrong, headers=headers
    )
    assert response.status_code == 429
