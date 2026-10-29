"""Pruebas unitarias de domain/business_days.py (RF-33)."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.business_days import (
    add_business_days,
    easter_sunday,
    is_business_day,
    quote_valid_until,
)

MADRID = ZoneInfo("Europe/Madrid")


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5))],
)
def test_easter_sunday(year: int, expected: date) -> None:
    assert easter_sunday(year) == expected


def test_weekends_and_national_holidays_are_not_business_days() -> None:
    assert not is_business_day(date(2026, 10, 31))  # sábado
    assert not is_business_day(date(2026, 11, 1))  # domingo y Todos los Santos
    assert not is_business_day(date(2026, 10, 12))  # lunes, Fiesta Nacional
    assert not is_business_day(date(2026, 4, 3))  # Viernes Santo
    assert is_business_day(date(2026, 4, 2))  # Jueves Santo: autonómico, cuenta
    assert is_business_day(date(2026, 10, 29))


def test_twelve_business_days_skip_weekends_and_the_day_of_sending() -> None:
    # Jueves 29 de octubre de 2026: el viernes 30 es el primero, y luego dos
    # semanas enteras (del 2 al 13 de noviembre, diez días): el duodécimo es el
    # lunes 16. El 1 de noviembre es festivo, pero cae en domingo.
    assert add_business_days(date(2026, 10, 29), 12) == date(2026, 11, 16)


def test_holidays_in_the_middle_push_the_date() -> None:
    # Desde el 1 de diciembre de 2026: el 7 es lunes (no festivo nacional, aunque
    # muchas comunidades trasladan el 6), el 8 es la Inmaculada y el 25 Navidad.
    # 12 días hábiles: 2, 3, 4, 7, 9, 10, 11, 14, 15, 16, 17, 18.
    assert add_business_days(date(2026, 12, 1), 12) == date(2026, 12, 18)


def test_the_validity_ends_at_midnight_of_the_workshop() -> None:
    # Vale todo el lunes 16: deja de valer a la medianoche del 17 en Madrid.
    sent = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    assert quote_valid_until(sent, "Europe/Madrid", 12) == datetime(
        2026, 11, 17, 0, 0, tzinfo=MADRID
    )


def test_the_day_of_sending_is_the_workshop_day_not_the_utc_day() -> None:
    # 23:30 UTC del jueves 29 son las 00:30 del viernes 30 en Madrid: el envío
    # es del viernes, y el plazo empieza el lunes 2.
    sent = datetime(2026, 10, 29, 23, 30, tzinfo=UTC)
    until = quote_valid_until(sent, "Europe/Madrid", 12)
    assert until.astimezone(MADRID).date() == date(2026, 11, 18)


def test_a_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError):
        quote_valid_until(datetime(2026, 10, 29), "Europe/Madrid", 12)


@given(
    st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)),
    st.integers(min_value=12, max_value=120),
)
def test_the_validity_has_exactly_the_business_days_asked(
    start: date, days: int
) -> None:
    """Entre el día del envío (excluido) y el último (incluido) hay exactamente
    `days` días hábiles, y el último lo es."""
    end = add_business_days(start, days)
    span = (end - start).days
    counted = sum(
        is_business_day(start + timedelta(days=n)) for n in range(1, span + 1)
    )
    assert counted == days
    assert is_business_day(end)
