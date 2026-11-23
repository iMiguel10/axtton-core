# Registro de cambios

Lo mantiene [release-please](https://github.com/googleapis/release-please) a partir de los commits convencionales de `main` (`feat:` son novedades, `fix:` correcciones): no se edita a mano. Cómo se publica una versión: [Versionado](docs/guias/versionado.md).

Las dos primeras versiones se escribieron a mano, resumidas por fase, al empezar a versionar.

## [0.7.0](https://github.com/iMiguel10/axtton-core/compare/v0.6.0...v0.7.0) (2026-11-23)


### Novedades

* **delivery:** km al entregar y resumen de entrega con su garantía (F6 paso 4, RF-53, RF-55) ([#43](https://github.com/iMiguel10/axtton-core/issues/43)) ([5117c50](https://github.com/iMiguel10/axtton-core/commit/5117c503cbedf51ddb391e4e4b0b9bf90da11957))
* **demo:** hojas firmadas, km de entrega e informe con dos titulares en la demo (F6 paso 7) ([#46](https://github.com/iMiguel10/axtton-core/issues/46)) ([3eff600](https://github.com/iMiguel10/axtton-core/commit/3eff60031e449685f1effc0fb349f8360545916c))
* **portal:** hoja firmada, resumen de entrega y garantía en el portal (F6 paso 6, RF-54, RF-53) ([#45](https://github.com/iMiguel10/axtton-core/issues/45)) ([5380e8f](https://github.com/iMiguel10/axtton-core/commit/5380e8f7b224ba670ba81411539582ecdca21349))
* **reception:** datos de recepción del resguardo y hoja firmada inmutable (F6 paso 1, RF-51, RF-52) ([#38](https://github.com/iMiguel10/axtton-core/issues/38)) ([ede845a](https://github.com/iMiguel10/axtton-core/commit/ede845a4aa1b5130283c54185a8ffa5890fbb0e8))
* **reception:** firmar la hoja de recepción en pantalla o en papel (F6 paso 2, RF-52, RF-27) ([#40](https://github.com/iMiguel10/axtton-core/issues/40)) ([0df10b7](https://github.com/iMiguel10/axtton-core/commit/0df10b7a0e3040c997cc52b517eaa83e439d8185))
* **reception:** PDF de la hoja de recepción, sin firmar o desde su copia firmada (F6 paso 3, RF-51, RF-55) ([#41](https://github.com/iMiguel10/axtton-core/issues/41)) ([b1e4a75](https://github.com/iMiguel10/axtton-core/commit/b1e4a75945794a29d4e27c0ac5bb038438181881))
* **vehicles:** informe de actuaciones del vehículo (F6 paso 5, RF-18, RNF-52) ([#44](https://github.com/iMiguel10/axtton-core/issues/44)) ([21c0497](https://github.com/iMiguel10/axtton-core/commit/21c04978c031d91406825bf97c58b21c58efb66d))


### Correcciones

* **demo:** fechas de la demo en el calendario del taller, también a medianoche ([#42](https://github.com/iMiguel10/axtton-core/issues/42)) ([cc648a3](https://github.com/iMiguel10/axtton-core/commit/cc648a3a1ffb8f219599345ed00fe9ad4850f749))
* **reception:** cierre de F6, con lo que encontró qa-verifier (F6 paso 8) ([#47](https://github.com/iMiguel10/axtton-core/issues/47)) ([05a198f](https://github.com/iMiguel10/axtton-core/commit/05a198ff8843f3847db92340de76527065212ff4))

## [0.6.0](https://github.com/iMiguel10/axtton-core/compare/v0.5.0...v0.6.0) (2026-11-18)


### Novedades

* **email:** envío SMTP paso a paso que dice si el correo salió (F5 paso 3, RF-62, RF-68) ([#31](https://github.com/iMiguel10/axtton-core/issues/31)) ([b65236a](https://github.com/iMiguel10/axtton-core/commit/b65236af8ac0e2c2ae05f1ed4b80ec7f0b4da140))
* **notifications:** aviso al cliente de presupuesto enviado y anulado (F5 paso 5, RF-60) ([#33](https://github.com/iMiguel10/axtton-core/issues/33)) ([6f2810d](https://github.com/iMiguel10/axtton-core/commit/6f2810d8786d8fc302cd35fc091993ece76c9779))
* **notifications:** aviso al cliente de vehículo listo para recoger (F5 paso 6, RF-60) ([#34](https://github.com/iMiguel10/axtton-core/issues/34)) ([fe4347f](https://github.com/iMiguel10/axtton-core/commit/fe4347f1242912b1dad4918deb658fd25b5cb277))
* **notifications:** la bandeja de avisos, con reintentos y sin duplicados (F5 paso 4, RF-62) ([#32](https://github.com/iMiguel10/axtton-core/issues/32)) ([c575a34](https://github.com/iMiguel10/axtton-core/commit/c575a3450cc5db0b213130ea7101c16694ce575e))
* **notifications:** lo que ve el taller de sus avisos al cliente (F5 paso 7, RF-63, RF-69) ([#35](https://github.com/iMiguel10/axtton-core/issues/35)) ([dc7e2f9](https://github.com/iMiguel10/axtton-core/commit/dc7e2f9c55e87656f264786948c38b1844c0615d))
* **portal:** el enlace de acceso al portal lo envía el worker, con reintentos (F5 paso 8, RF-40, RF-41) ([#36](https://github.com/iMiguel10/axtton-core/issues/36)) ([e6e273c](https://github.com/iMiguel10/axtton-core/commit/e6e273c0cd6cab2c966b00a5bf11f3602ec0b205))
* **quotes:** el worker marca como caducados los presupuestos fuera de plazo (F5 paso 2, RF-33) ([#30](https://github.com/iMiguel10/axtton-core/issues/30)) ([fff5d1d](https://github.com/iMiguel10/axtton-core/commit/fff5d1de760c68aa3ceae675f4ec9c3e9ed1d1bd))
* **worker:** el worker de SAQ y el borrado de los enlaces del portal caducados (F5 paso 1) ([#27](https://github.com/iMiguel10/axtton-core/issues/27)) ([f8aef7d](https://github.com/iMiguel10/axtton-core/commit/f8aef7d8c05f467bfc11cccec7c674dc0d00d1c8))


### Correcciones

* **deploy:** el worker sin entrypoint vacío, que Coolify no acepta ([#29](https://github.com/iMiguel10/axtton-core/issues/29)) ([1b8ffdd](https://github.com/iMiguel10/axtton-core/commit/1b8ffddfd689571643e2dcf3961acf0d05111c76))
* **notifications:** cierre de F5, con lo que encontró qa-verifier (F5 paso 9) ([#37](https://github.com/iMiguel10/axtton-core/issues/37)) ([7400b3c](https://github.com/iMiguel10/axtton-core/commit/7400b3ceeef0ea8a7c2eb65d750d3091f8e53b65))

## [0.5.0](https://github.com/iMiguel10/axtton-core/compare/v0.4.0...v0.5.0) (2026-11-11)


### Novedades

* **portal:** el cliente aprueba o rechaza el presupuesto (F4 paso 5, RF-34, RF-36) ([#22](https://github.com/iMiguel10/axtton-core/issues/22)) ([365a472](https://github.com/iMiguel10/axtton-core/commit/365a47258a164746b35a6d60e89ca4d5510f9997))
* **portal:** el PDF de cada versión del presupuesto para el cliente (F4 paso 6, RF-54) ([#23](https://github.com/iMiguel10/axtton-core/issues/23)) ([02fd85b](https://github.com/iMiguel10/axtton-core/commit/02fd85b2cd58f683430d579aa4faf77180e0e2e9))
* **portal:** enlace mágico pedido desde la entrada de cada taller (F4 paso 1, RF-40) ([#17](https://github.com/iMiguel10/axtton-core/issues/17)) ([f1b03cc](https://github.com/iMiguel10/axtton-core/commit/f1b03cc7e9990f77f9a40e8cd3bc041badf4aca1))
* **portal:** entrar en el portal de la demo sin correo, y el portal en sus datos (F4 paso 8) ([#25](https://github.com/iMiguel10/axtton-core/issues/25)) ([899a6ba](https://github.com/iMiguel10/axtton-core/commit/899a6badf158036ea77aacaacede77d8ee165d10))
* **portal:** la dirección corta del taller, su logotipo en la entrada y la IP para el administrador (F4 paso 7) ([#24](https://github.com/iMiguel10/axtton-core/issues/24)) ([d022fe1](https://github.com/iMiguel10/axtton-core/commit/d022fe1233f4aa6f017f213fd266cbe6764e1805))
* **portal:** la sesión del cliente, con revocación por taller y 30 días (F4 paso 2, RF-47, T7) ([#19](https://github.com/iMiguel10/axtton-core/issues/19)) ([c2f47c5](https://github.com/iMiguel10/axtton-core/commit/c2f47c5323e5111bc9868f0da45ce8f477813715))
* **portal:** los estados que ve el cliente y el aviso de fecha pasada (F4 paso 3, RF-80) ([#20](https://github.com/iMiguel10/axtton-core/issues/20)) ([8b3b077](https://github.com/iMiguel10/axtton-core/commit/8b3b077119fa505873c3e8dcb0600c205b7c2c7e))
* **portal:** los vehículos y las órdenes del cliente (F4 paso 4, RF-42 a RF-44, T4) ([#21](https://github.com/iMiguel10/axtton-core/issues/21)) ([6304a8c](https://github.com/iMiguel10/axtton-core/commit/6304a8c69a16cb40eeeb2efd125719a223159b71))


### Correcciones

* cierre de F4, sin cerrar la sesión de otro taller al revocar las de uno ([#26](https://github.com/iMiguel10/axtton-core/issues/26)) ([bd44edc](https://github.com/iMiguel10/axtton-core/commit/bd44edc2f7f8e9b2ce8f427365c03116e6b198a3))

## [0.4.0](https://github.com/iMiguel10/axtton-core/compare/v0.3.0...v0.4.0) (2026-11-03)


### Novedades

* **orders:** filtros del listado por estado, responsable y fecha prevista (F3 paso 8, RF-24) ([#15](https://github.com/iMiguel10/axtton-core/issues/15)) ([cc84885](https://github.com/iMiguel10/axtton-core/commit/cc84885630edbf9881b8f7f40a28d9136182ad71))
* **quotes:** borrador del presupuesto, su editor y el listado (F3 paso 4) ([#11](https://github.com/iMiguel10/axtton-core/issues/11)) ([502c600](https://github.com/iMiguel10/axtton-core/commit/502c6000037784dd0e14be865797be76312fde3e))
* **quotes:** decisión registrada por el taller e importe a cobrar (F3 paso 6) ([#13](https://github.com/iMiguel10/axtton-core/issues/13)) ([e2badef](https://github.com/iMiguel10/axtton-core/commit/e2badef5467f5a5deca719c761ee14426e707a1a))
* **quotes:** enviar, renovar y anular el presupuesto (F3 paso 5) ([#12](https://github.com/iMiguel10/axtton-core/issues/12)) ([7ec665b](https://github.com/iMiguel10/axtton-core/commit/7ec665b080358a4023a4f2dcb1cf07659e5a572f))
* **quotes:** PDF del presupuesto y vista previa del borrador (F3 paso 7) ([#14](https://github.com/iMiguel10/axtton-core/issues/14)) ([1759f91](https://github.com/iMiguel10/axtton-core/commit/1759f910f5a07d222778f7874e50deb8d077c4df))
* **quotes:** regla única de los totales y validez en días hábiles (F3 paso 2) ([#9](https://github.com/iMiguel10/axtton-core/issues/9)) ([5aa6e48](https://github.com/iMiguel10/axtton-core/commit/5aa6e48e6ac0e9e7cba068f1edad598bb3a1d3f6))
* **quotes:** tablas de presupuesto inmutables al enviarse (F3 paso 3) ([#10](https://github.com/iMiguel10/axtton-core/issues/10)) ([bb44e77](https://github.com/iMiguel10/axtton-core/commit/bb44e7712fea6f2c43fb9f66e611cbf862ea0e27))
* **settings:** datos del taller, logotipo y tarifas de mano de obra (F3 paso 1, RF-02) ([#8](https://github.com/iMiguel10/axtton-core/issues/8)) ([d89f59b](https://github.com/iMiguel10/axtton-core/commit/d89f59b762e1c8e30b536935b66faf46cf182ea2))


### Correcciones

* cierre de F3, con las decisiones inmutables también para el dueño ([#16](https://github.com/iMiguel10/axtton-core/issues/16)) ([fcab7a5](https://github.com/iMiguel10/axtton-core/commit/fcab7a50bdb862fcb0ebe1da77b8bc88bc29a023))
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
