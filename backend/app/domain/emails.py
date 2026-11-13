"""El contenido de los emails de la plataforma (RF-68), sin su forma.

Aquí se decide qué dice cada email: el saludo, los párrafos, el botón y la nota
del final. Cómo se ve (el HTML con la marca y el texto plano de respaldo) lo
pone infra/email.py. Así las pruebas comprueban las palabras sin depender de
la maqueta, y la maqueta es una sola para todos.
"""

from dataclasses import dataclass
from datetime import date

from app.domain.clients import Language
from app.domain.money import format_eur


@dataclass(frozen=True)
class EmailContent:
    subject: str
    greeting: str
    paragraphs: tuple[str, ...]
    # El botón: lo único que se espera que haga quien lo recibe.
    action_label: str
    action_url: str
    # Lo pequeño del final: caducidad, "si no lo esperabas".
    footnote: str
    # El taller que lo envía; None si es de la plataforma (el superadministrador,
    # la recuperación de contraseña). Sale en la cabecera y en el remitente.
    workshop_name: str | None = None
    # La dirección de respuesta del taller (RF-68): si el cliente contesta, le
    # llega al taller y no a la plataforma. La ponen los avisos al cliente (F5).
    reply_to: str | None = None
    # El idioma del email: el del cliente en sus avisos (F5 paso 5); la
    # plataforma escribe en español.
    language: Language = Language.ES


def invitation_email(
    *, employee_name: str, workshop_name: str, link: str, first_admin: bool
) -> EmailContent:
    """La invitación a un taller: al primer administrador o a un empleado."""
    intro = (
        f"Se ha dado de alta el taller {workshop_name} y eres su administrador."
        if first_admin
        else f"Te han invitado a trabajar en {workshop_name}."
    )
    return EmailContent(
        subject=f"Te han dado acceso a {workshop_name} en AXTTON CORE",
        greeting=f"Hola, {employee_name}:",
        paragraphs=(
            intro,
            "Para activar tu acceso, elige tu contraseña desde este enlace.",
        ),
        action_label="Activar mi acceso",
        action_url=link,
        footnote="El enlace caduca en 7 días. Si no esperabas este mensaje, ignóralo.",
        workshop_name=workshop_name,
    )


def superadmin_invitation_email(*, link: str) -> EmailContent:
    """La invitación a ser superadministrador (RF-110)."""
    return EmailContent(
        subject="Te han invitado a administrar AXTTON CORE",
        greeting="Hola:",
        paragraphs=(
            (
                "Te han invitado a ser superadministrador de esta instalación de"
                " AXTTON CORE: darás de alta talleres y gestionarás sus límites,"
                " sin acceso a lo que ocurre dentro de cada uno."
            ),
        ),
        action_label="Crear mi cuenta",
        action_url=link,
        footnote="El enlace caduca en 7 días. Si no esperabas este mensaje, ignóralo.",
    )


def password_reset_email(*, link: str) -> EmailContent:
    """La recuperación de contraseña (RF-121). Es de la plataforma: la misma
    cuenta puede trabajar en varios talleres."""
    return EmailContent(
        subject="Recupera tu contraseña de AXTTON CORE",
        greeting="Hola:",
        paragraphs=(
            "Has pedido cambiar tu contraseña. Elige una nueva desde este enlace.",
        ),
        action_label="Elegir una contraseña nueva",
        action_url=link,
        footnote=(
            "El enlace caduca en una hora y solo sirve una vez. Si no lo has pedido"
            " tú, ignora este mensaje: tu contraseña no cambia."
        ),
    )


def portal_access_email(*, workshop_name: str, link: str) -> EmailContent:
    """El acceso al portal de un taller (RF-40): se pidió desde su página de
    entrada, y el enlace solo abre ese taller (RF-45, decisión 0006)."""
    return EmailContent(
        subject=f"Tu acceso al portal de {workshop_name}",
        greeting="Hola:",
        paragraphs=(
            (
                "Has pedido entrar en el portal, donde puedes seguir la reparación"
                " de tu vehículo y responder a sus presupuestos."
            ),
        ),
        action_label="Entrar en el portal",
        action_url=link,
        footnote=(
            "El enlace caduca en 15 minutos y solo sirve una vez. Si no lo has"
            " pedido tú, ignora este mensaje: nadie puede entrar sin él."
        ),
        workshop_name=workshop_name,
    )


# --- Los avisos al cliente (F5 paso 5, RF-60) ------------------------------------
# En el idioma del cliente (`clients.language`). Lo que cuentan es lo que el
# cliente ya puede ver en el portal; nada interno (ni el motivo de una anulación,
# como en su PDF).

_MONTHS = {
    Language.ES: [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ],
    Language.EN: [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
}


def format_day(day: date, language: Language) -> str:
    """Un día del calendario para una persona: "12 de diciembre de 2026" o
    "December 12, 2026"."""
    month = _MONTHS[language][day.month - 1]
    if language == Language.EN:
        return f"{month} {day.day}, {day.year}"
    return f"{day.day} de {month} de {day.year}"


def format_money(cents: int, language: Language) -> str:
    """10346 → "103,46 €" o "€103.46"."""
    if language == Language.EN:
        sign = "-" if cents < 0 else ""
        euros, rest = divmod(abs(cents), 100)
        return f"{sign}€{euros:,}.{rest:02d}"
    return format_eur(cents)


@dataclass(frozen=True)
class NoticeContext:
    """Lo común a los avisos de una orden: de qué taller, a quién y adónde lleva
    el botón (la entrada del portal del taller, que abre la orden)."""

    language: Language
    workshop_name: str
    reply_to: str | None
    order_code: str
    vehicle: str  # "1234 BCD · Peugeot 308"
    link: str


_FOOTNOTE = {
    Language.ES: "Si tienes alguna duda, responde a este correo: le llega al taller.",
    Language.EN: (
        "If you have any questions, reply to this email: it goes to the workshop."
    ),
}


def _notice(
    notice: NoticeContext,
    *,
    subject: str,
    paragraphs: tuple[str, ...],
    action_label: str,
) -> EmailContent:
    return EmailContent(
        subject=subject,
        greeting="Hello," if notice.language == Language.EN else "Hola:",
        paragraphs=paragraphs,
        action_label=action_label,
        action_url=notice.link,
        footnote=_FOOTNOTE[notice.language],
        workshop_name=notice.workshop_name,
        reply_to=notice.reply_to,
        language=notice.language,
    )


def quote_sent_email(
    notice: NoticeContext, *, version_no: int, total_cents: int, last_valid_day: date
) -> EmailContent:
    """El presupuesto enviado (RF-60): qué cuesta, hasta cuándo vale y dónde
    verlo y responder."""
    total = format_money(total_cents, notice.language)
    until = format_day(last_valid_day, notice.language)
    shop, vehicle, code = notice.workshop_name, notice.vehicle, notice.order_code
    if notice.language == Language.EN:
        return _notice(
            notice,
            subject=f"Your quote from {shop} for {vehicle}",
            paragraphs=(
                (
                    f"{shop} has sent you a quote for the repair of your vehicle"
                    f" {vehicle} (order {code}, version {version_no})."
                ),
                f"Total: {total}, VAT included. It is valid until {until}.",
                (
                    "You can read it in full, download it and accept or reject it in"
                    " the portal."
                ),
            ),
            action_label="View the quote",
        )
    return _notice(
        notice,
        subject=f"Tu presupuesto de {shop} para {vehicle}",
        paragraphs=(
            (
                f"{shop} te ha enviado el presupuesto de la reparación de tu vehículo"
                f" {vehicle} (orden {code}, versión {version_no})."
            ),
            f"Total: {total}, IVA incluido. Es válido hasta el {until}.",
            "En el portal puedes leerlo entero, descargarlo y aceptarlo o rechazarlo.",
        ),
        action_label="Ver el presupuesto",
    )


def quote_cancelled_email(notice: NoticeContext, *, version_no: int) -> EmailContent:
    """El presupuesto anulado por el taller (especificación §6): ya no se puede
    aceptar. Sin el motivo, que es interno."""
    shop, vehicle, code = notice.workshop_name, notice.vehicle, notice.order_code
    if notice.language == Language.EN:
        return _notice(
            notice,
            subject=f"{shop} has withdrawn its quote for {vehicle}",
            paragraphs=(
                (
                    f"{shop} has withdrawn version {version_no} of the quote for your"
                    f" vehicle {vehicle} (order {code}). It can no longer be accepted."
                ),
                (
                    "If the workshop sends you a new one, you will receive it by email"
                    " and in the portal."
                ),
            ),
            action_label="View the order",
        )
    return _notice(
        notice,
        subject=f"{shop} ha retirado su presupuesto para {vehicle}",
        paragraphs=(
            (
                f"{shop} ha retirado la versión {version_no} del presupuesto de tu"
                f" vehículo {vehicle} (orden {code}). Ya no se puede aceptar."
            ),
            "Si el taller te envía uno nuevo, te llegará por correo y en el portal.",
        ),
        action_label="Ver la orden",
    )


def vehicle_ready_email(
    notice: NoticeContext,
    *,
    unrepaired: bool,
    address: str | None,
    phone: str | None,
) -> EmailContent:
    """El vehículo listo para recoger (RF-60). "Sin reparar" (especificación
    §6) se dice tal cual: es lo que el cliente ve también en el portal."""
    shop, vehicle, code = notice.workshop_name, notice.vehicle, notice.order_code
    if notice.language == Language.EN:
        where = [
            *([f"Address: {address}."] if address else []),
            *([f"Phone: {phone}."] if phone else []),
        ]
        first = (
            f"{shop} has not repaired your vehicle {vehicle} (order {code}), and"
            " you can now pick it up. You will find the details in the portal."
            if unrepaired
            else f"{shop} has finished with your vehicle {vehicle} (order {code})."
            " You can now pick it up."
        )
        return _notice(
            notice,
            subject=(
                f"Your {vehicle} is ready to pick up, unrepaired"
                if unrepaired
                else f"Your {vehicle} is ready to pick up"
            ),
            paragraphs=(first, *([" ".join(where)] if where else [])),
            action_label="View the order",
        )
    where = [
        *([f"Dirección: {address}."] if address else []),
        *([f"Teléfono: {phone}."] if phone else []),
    ]
    first = (
        f"{shop} no ha reparado tu vehículo {vehicle} (orden {code}) y ya puedes"
        " pasar a recogerlo. En el portal tienes el detalle."
        if unrepaired
        else f"{shop} ha terminado con tu vehículo {vehicle} (orden {code}). Ya"
        " puedes pasar a recogerlo."
    )
    return _notice(
        notice,
        subject=(
            f"Tu {vehicle} está listo para recoger, sin reparar"
            if unrepaired
            else f"Tu {vehicle} está listo para recoger"
        ),
        paragraphs=(first, *([" ".join(where)] if where else [])),
        action_label="Ver la orden",
    )
