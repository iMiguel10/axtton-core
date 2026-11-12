"""Reglas de capas comprobadas leyendo los imports (CLAUDE.md §5).

"La regla única: si habla con la BD, vive en repositories/; si decide, en
services/ o domain/; si cruza talleres, en platform/." Estas pruebas la hacen
verificable en lugar de aspiracional.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def imports_of(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def violations(layer: str, forbidden: tuple[str, ...]) -> dict[str, set[str]]:
    found = {}
    files = list((APP / layer).rglob("*.py"))
    assert files, f"no hay ficheros en app/{layer}"  # prueba de control
    for path in files:
        bad = {m for m in imports_of(path) if m.startswith(forbidden)}
        if bad:
            found[path.relative_to(APP).as_posix()] = bad
    return found


def test_services_do_not_know_about_http_nor_cross_workshops() -> None:
    assert (
        violations("services", ("fastapi", "starlette", "app.platform", "app.api"))
        == {}
    )


def test_domain_has_no_io() -> None:
    assert (
        violations(
            "domain",
            (
                "sqlalchemy",
                "fastapi",
                "httpx",
                "aiosmtplib",
                "supertokens_python",
                "app.infra",
                "app.repositories",
                "app.models",
            ),
        )
        == {}
    )


def test_repositories_do_not_decide_nor_cross_workshops() -> None:
    assert (
        violations(
            "repositories", ("app.services", "app.platform", "app.api", "fastapi")
        )
        == {}
    )


def test_jobs_are_thin_and_only_cross_workshops_through_the_scheduler() -> None:
    """Un trabajo del worker no consulta la BD ni decide (F5, arquitectura §8):
    busca con el planificador y le pasa cada elemento a un service. De
    app.platform solo puede usar el planificador, que solo busca (§4)."""
    assert (
        violations(
            "jobs",
            ("sqlalchemy", "app.repositories", "app.models", "fastapi", "app.api"),
        )
        == {}
    )
    crossing = {
        path.relative_to(APP).as_posix(): module
        for path in (APP / "jobs").rglob("*.py")
        for module in imports_of(path)
        if module.startswith("app.platform") and module != "app.platform.scheduler"
    }
    assert crossing == {}
