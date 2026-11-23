"""Lo congelado en jsonb se compara como texto (cierre de F6)

Lo encontró qa-verifier al cerrar F6: en `jsonb`, `{"km": 1}` es igual a
`{"km": 1.0}`, así que comparar con `IS DISTINCT FROM` dejaba reescribir los
números de lo congelado sin cambiar su valor para Postgres, pero sí lo que se
lee: el PDF de la hoja firmada sacaba "123.456.0 km" y dejaba de salir idéntico
(RF-55, invariante 6).

Afecta a dos triggers. El de la hoja firmada (`reception_sheets_frozen`) compara
`snapshot` y `signature`, y la plataforma o el dueño podían colar un cambio así
al vaciar lo personal de un cliente anonimizado. El del presupuesto enviado
(`quotes_frozen_after_send`) compara la fila entera en jsonb, con
`vehicle_snapshot` dentro, con cualquier rol que pueda actualizarla. Con
`::text`, la forma escrita de un jsonb es canónica salvo en esto: guarda la
escala de cada número.

Se cambia solo esa comparación, sobre la definición viva de cada función, y la
migración falla si no encuentra el texto que cambia: así no se reescriben a mano
dos funciones largas (y no se desalinean de lo que hay).

Revision ID: 0026frozenjson
Revises: 0025deliverykm
Create Date: 2026-11-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026frozenjson"
down_revision: str | None = "0025deliverykm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUOTES_KEPT = "ARRAY['status', 'cancel_reason', 'version', 'updated_at'])"
# (función, texto de antes, texto de después), cada uno exactamente una vez.
CHANGES = (
    (
        "quotes_frozen_after_send()",
        f"(to_jsonb(NEW) - {QUOTES_KEPT}",
        f"(to_jsonb(NEW) - {QUOTES_KEPT}::text",
    ),
    (
        "quotes_frozen_after_send()",
        f"(to_jsonb(OLD) - {QUOTES_KEPT}",
        f"(to_jsonb(OLD) - {QUOTES_KEPT}::text",
    ),
    (
        "reception_sheets_frozen()",
        "NEW.snapshot, NEW.quote_waived, NEW.signature,",
        "NEW.snapshot::text, NEW.quote_waived, NEW.signature::text,",
    ),
    (
        "reception_sheets_frozen()",
        "OLD.snapshot, OLD.quote_waived, OLD.signature,",
        "OLD.snapshot::text, OLD.quote_waived, OLD.signature::text,",
    ),
)


def _replace(function: str, old: str, new: str) -> None:
    op.execute(
        f"""
        DO $migration$
        DECLARE
            source text := pg_get_functiondef('{function}'::regprocedure);
            changed text;
        BEGIN
            -- Exactamente una vez: ni falta, ni se cambiaría otra cosa.
            IF array_length(string_to_array(source, $old${old}$old$), 1) <> 2 THEN
                RAISE EXCEPTION '{function}: no se encontró una sola vez el texto a cambiar';
            END IF;
            changed := replace(source, $old${old}$old$, $new${new}$new$);
            EXECUTE changed;
        END
        $migration$
        """
    )


def upgrade() -> None:
    for function, old, new in CHANGES:
        _replace(function, old, new)


def downgrade() -> None:
    for function, old, new in reversed(CHANGES):
        _replace(function, new, old)
