# Registro de cambios

Lo mantiene [release-please](https://github.com/googleapis/release-please) a partir de los commits convencionales de `main` (`feat:` son novedades, `fix:` correcciones): no se edita a mano. Cómo se publica una versión: [Versionado](docs/guias/versionado.md).

Las dos primeras versiones se escribieron a mano, resumidas por fase, al empezar a versionar.

## [0.2.0](https://github.com/iMiguel10/axtton-core/compare/v0.1.0...v0.2.0) (2026-10-26)

F1: la base sobre la que se construye todo lo demás.

### Novedades

* Autenticación con SuperTokens para el personal y el superadministrador, con el actor fijado al crear la sesión y los tres prefijos de API cerrados entre sí.
* Superadministrador: alta de talleres con invitación al primer administrador, listado, desactivación e invitación de otros superadministradores (RF-110, RF-114).
* Modo de instalación de uno o varios talleres (RF-111), taller activo validado en cada petición y selector de talleres.
* Empleados, roles y matriz de permisos; invitaciones por email.
* Recuperar y cambiar la contraseña y cerrar las otras sesiones (RF-122, RF-123).
* Registro de auditoría del taller y de la plataforma (RNF-16).
* Límite de peticiones con Valkey (RNF-06).
* RLS en todas las tablas de un taller, con sus pruebas adversas, y CI en GitHub Actions.
* Interfaz en español e inglés con las pantallas de acceso, invitación, empleados, mi cuenta y talleres.

## 0.1.0 (2026-10-24)

F0: esqueleto vertical para validar el diseño, retirado al empezar F1.

### Novedades

* Orden, presupuesto de una línea y aprobación por enlace secreto.
* Los tres roles de Postgres y el primer RLS de verdad.
* PDF del presupuesto con WeasyPrint.
* Frontend mínimo con la aplicación del taller y el portal.
