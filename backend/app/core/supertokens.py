"""Inicialización del SDK de SuperTokens (arquitectura A4, §2).

Debe ejecutarse antes de crear la app de FastAPI. El core solo es accesible por
la red interna de Docker.
"""

from typing import Any

from supertokens_python import InputAppInfo, SupertokensConfig, init
from supertokens_python.ingredients.emaildelivery.types import EmailDeliveryConfig
from supertokens_python.recipe import emailpassword, session
from supertokens_python.recipe.emailpassword import EmailPasswordOverrideConfig
from supertokens_python.recipe.emailpassword.interfaces import APIInterface
from supertokens_python.recipe.session import SessionOverrideConfig
from supertokens_python.types.response import GeneralErrorResponse

from app.core.auth_emails import PlatformPasswordResetEmail, password_reset_effects
from app.core.config import get_settings
from app.core.sessions import emailpassword_override, session_override

# Las rutas de SuperTokens cuelgan de /api, como todo lo de la API: así el proxy
# (Vite en desarrollo, el servidor web en producción) solo tiene que reenviar /api.
AUTH_BASE_PATH = "/api/auth"


def _no_public_signup(original: APIInterface) -> APIInterface:
    """No hay registro abierto (RF-01): el personal entra siempre por invitación
    y el superadministrador se crea con un comando de servidor.

    Se anula la operación, no una URL: SuperTokens atiende el registro en varias
    rutas (/signup, /public/signup...), y bloquear una dejaría las otras abiertas
    (trampa encontrada en Applications Tracker). Las cuentas se crean desde el
    backend con la función de la receta, que no pasa por aquí.
    """

    async def sign_up_post(*_args: Any, **_kwargs: Any) -> GeneralErrorResponse:
        return GeneralErrorResponse("signup_disabled")

    original.sign_up_post = sign_up_post  # type: ignore[method-assign]
    return original


def init_supertokens() -> None:
    settings = get_settings()
    init(
        app_info=InputAppInfo(
            app_name="AXTTON CORE",
            # Un solo dominio: la API se ve desde el navegador en el mismo origen
            # que la web, así que las cookies de sesión son de primera parte.
            api_domain=settings.app_url,
            website_domain=settings.app_url,
            api_base_path=AUTH_BASE_PATH,
            website_base_path="/",
        ),
        supertokens_config=SupertokensConfig(
            connection_uri=settings.supertokens_connection_uri,
            api_key=settings.supertokens_api_key,
        ),
        framework="fastapi",
        recipe_list=[
            # Cookies httpOnly en el navegador y Bearer fuera de él (decisión 0003
            # de Applications Tracker): es la costura para las apps móviles.
            session.init(override=SessionOverrideConfig(functions=session_override)),
            emailpassword.init(
                # El email de recuperación sale por nuestro SMTP, no por el
                # servicio de SuperTokens (auth_emails.py).
                email_delivery=EmailDeliveryConfig(
                    service=PlatformPasswordResetEmail()
                ),
                override=EmailPasswordOverrideConfig(
                    functions=emailpassword_override,
                    apis=lambda original: password_reset_effects(
                        _no_public_signup(original)
                    ),
                ),
            ),
        ],
        mode="asgi",
        # Sin envío de datos de uso a SuperTokens.
        telemetry=False,
    )
