# Registro de cambios

Lo mantiene [release-please](https://github.com/googleapis/release-please) a partir de los commits convencionales de `main` (`feat:` son novedades, `fix:` correcciones): no se edita a mano. Cómo se publica una versión: [Versionado](docs/guias/versionado.md).

Las dos primeras versiones se escribieron a mano, resumidas por fase, al empezar a versionar.

## [0.4.0](https://github.com/iMiguel10/axtton-core/compare/v0.3.0...v0.4.0) (2026-10-30)


### Novedades

* **quotes:** borrador del presupuesto, su editor y el listado (F3 paso 4) ([#11](https://github.com/iMiguel10/axtton-core/issues/11)) ([502c600](https://github.com/iMiguel10/axtton-core/commit/502c6000037784dd0e14be865797be76312fde3e))
* **quotes:** enviar, renovar y anular el presupuesto (F3 paso 5) ([#12](https://github.com/iMiguel10/axtton-core/issues/12)) ([7ec665b](https://github.com/iMiguel10/axtton-core/commit/7ec665b080358a4023a4f2dcb1cf07659e5a572f))
* **quotes:** regla única de los totales y validez en días hábiles (F3 paso 2) ([#9](https://github.com/iMiguel10/axtton-core/issues/9)) ([5aa6e48](https://github.com/iMiguel10/axtton-core/commit/5aa6e48e6ac0e9e7cba068f1edad598bb3a1d3f6))
* **quotes:** tablas de presupuesto inmutables al enviarse (F3 paso 3) ([#10](https://github.com/iMiguel10/axtton-core/issues/10)) ([bb44e77](https://github.com/iMiguel10/axtton-core/commit/bb44e7712fea6f2c43fb9f66e611cbf862ea0e27))
* **settings:** datos del taller, logotipo y tarifas de mano de obra (F3 paso 1, RF-02) ([#8](https://github.com/iMiguel10/axtton-core/issues/8)) ([d89f59b](https://github.com/iMiguel10/axtton-core/commit/d89f59b762e1c8e30b536935b66faf46cf182ea2))


### Correcciones

* **demo:** la demo pública ya no tiene superadministrador ([#6](https://github.com/iMiguel10/axtton-core/issues/6)) ([57cb223](https://github.com/iMiguel10/axtton-core/commit/57cb2232a511d636f372ba8d5076f7aa4dcc725a))

## [0.3.0](https://github.com/iMiguel10/axtton-core/compare/v0.2.0...v0.3.0) (2026-10-28)


### Novedades

* **clients:** anonimizar a un cliente a petición suya (F2 paso 8, RF-15) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **clients:** clientes con email único por taller, edición y archivo (F2 paso 1, RF-10) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **demo:** datos de demostración que se recargan cada noche ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **deploy:** primer despliegue en Coolify (F2 paso 10) ([#3](https://github.com/iMiguel10/axtton-core/issues/3)) ([8a20a32](https://github.com/iMiguel10/axtton-core/commit/8a20a326c12646344f1b403004874223af6e3f66))
* **drafts:** borradores sin conexión que se reenvían al volver (F2 paso 7, RNF-22) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **limits:** límites de recursos por taller (F2 paso 9b, RF-114) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **orders:** ciclo de vida, reparación sin presupuesto y deshacer (F2 paso 4, RF-26, RF-27) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **orders:** cobro de órdenes cerradas y pendientes de cobro (F2 paso 8, RF-28, RF-29) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **orders:** diagnóstico versionado, notas internas y trabajos (F2 paso 5, RF-22 a RF-26) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **orders:** órdenes de trabajo con numeración por taller y año (F2 paso 3, RF-20, RF-21) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **search:** búsqueda única por matrícula, nombre y teléfono (F2 paso 6, RF-14) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **ui:** rediseño de la interfaz y correos con la marca (F2 paso 9) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* **vehicles:** vehículos y cambio de titular auditado (F2 paso 2, RF-11, RF-12, RF-13) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))
* versión de la aplicación y registro de cambios (F2 paso 9c) ([7297325](https://github.com/iMiguel10/axtton-core/commit/72973253540e391fd7a7ef8f0ebce46a347291e6))


### Correcciones

* cierre de F2, con el invariante 7 en la base de datos ([#4](https://github.com/iMiguel10/axtton-core/issues/4)) ([8f807ac](https://github.com/iMiguel10/axtton-core/commit/8f807ac9b5eb4c4ce7fc25a30f6612648b83888f))

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
