"""Días hábiles para la validez de un presupuesto (RF-33): sin base de datos.

La norma exige que un presupuesto valga como mínimo 12 días hábiles. Se cuentan
de lunes a viernes, sin los festivos nacionales: los de fecha fija y el Viernes
Santo, que es nacional aunque cambie de fecha. No se cuentan los autonómicos ni
los locales, ni los traslados a lunes de un festivo que cae en domingo, que
deciden las comunidades: para eso el taller puede ampliar el plazo, y la
pantalla de configuración lo dice. Contar de menos solo alarga la validez, que
es el lado seguro para el cliente.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# (mes, día): Año Nuevo, Reyes, Fiesta del Trabajo, Asunción, Fiesta Nacional,
# Todos los Santos, Constitución, Inmaculada y Navidad.
NATIONAL_FIXED_HOLIDAYS = frozenset(
    {(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)}
)


def easter_sunday(year: int) -> date:
    """Domingo de Pascua del calendario gregoriano (algoritmo anónimo, o de
    Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def is_national_holiday(day: date) -> bool:
    if (day.month, day.day) in NATIONAL_FIXED_HOLIDAYS:
        return True
    return day == easter_sunday(day.year) - timedelta(days=2)  # Viernes Santo


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and not is_national_holiday(day)


def add_business_days(start: date, days: int) -> date:
    """El día hábil número `days` contando desde el siguiente a `start`: el día
    del envío no cuenta, aunque sea hábil."""
    if days < 1:
        raise ValueError("days must be positive")
    day = start
    counted = 0
    while counted < days:
        day += timedelta(days=1)
        if is_business_day(day):
            counted += 1
    return day


def quote_valid_until(sent_at: datetime, timezone: str, days: int) -> datetime:
    """Hasta cuándo vale un presupuesto enviado en `sent_at`: hasta el final del
    último día hábil, en la zona del taller (R10).

    Devuelve el instante en que deja de valer, la medianoche en que empieza el
    día siguiente: vale mientras `ahora < valid_until`. El día del envío se toma
    en la zona del taller, no en UTC: a las 00:30 de Madrid, en UTC aún es el día
    anterior.
    """
    if sent_at.tzinfo is None:
        raise ValueError("sent_at must be timezone-aware")
    zone = ZoneInfo(timezone)
    sent_day = sent_at.astimezone(zone).date()
    last_day = add_business_days(sent_day, days)
    return datetime.combine(last_day + timedelta(days=1), time(), tzinfo=zone)
