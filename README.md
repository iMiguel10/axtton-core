# AXTTON CORE

**Gestión para talleres mecánicos, con un portal para que el cliente siga su reparación sin llamar.**

> **Estado: F2 terminada y desplegada ([lo aprendido](docs/arquitectura/f2-cierre.md)).** Hoy existe el núcleo operativo del taller: acceso del personal y del superadministrador, alta de talleres, roles, auditoría y aislamiento entre talleres (F1), y ahora clientes, vehículos con titularidad, órdenes con ciclo de vida e historial (con deshacer), diagnóstico, notas y trabajos, búsqueda única en el mostrador, borradores sin conexión, cobro, anonimización, límites por taller y la versión visible. **Todavía no hay** presupuestos (F3), portal del cliente (F4) ni avisos (F5).
>
> **Demo pública:** <https://axtton.imigueldev.duckdns.org>, que se recarga cada noche. Entra con `laura@demo.example.com` (administradora) o `javier@demo.example.com` (mecánico), contraseña pública `demo-axtton-2026`; el resto de cuentas, en la [guía de la demo](docs/guias/demo.md).

## Qué resuelve

En un taller, la información de cada coche está repartida entre papel, hojas de cálculo, mensajes y llamadas, y el cliente llama varias veces al día para preguntar cómo va. AXTTON CORE junta en un sitio el trabajo diario y resuelve muy bien un flujo concreto:

**se da cita → entra el coche → se diagnostica → se presupuesta → el cliente aprueba desde el móvil → se repara → se entrega**

- **Para el taller:** clientes, vehículos y su historial, citas, órdenes de trabajo, presupuestos con versiones, inventario básico, cobros pendientes y documentos generados (presupuesto, hoja de recepción firmada, resumen de entrega con su garantía).
- **Para el cliente:** un portal privado, sin contraseña (enlace por email), donde ve el estado de su coche, aprueba o rechaza el presupuesto y descarga sus documentos.

No es un programa de facturación, ni de compras, ni de reservas online: la especificación dice qué no es y por qué.

## Decisiones destacadas

- **Multi-taller con el aislamiento en la base de datos.** Cada fila lleva su taller. Las claves foráneas compuestas impiden mezclar datos de dos talleres, y **Row-Level Security** de PostgreSQL impide leerlos aunque una consulta olvide filtrar. Si nadie fija el taller, la consulta no ve nada; nunca ve todo.
- **Tres actores que no se cruzan.** Personal, clientes y superadministrador entran por SuperTokens con recetas distintas, y la API se parte en `/workshop`, `/portal` y `/admin`, cada prefijo cerrado a los otros dos desde el router. Una prueba recorre el OpenAPI para que ningún endpoint nuevo se quede fuera.
- **Quién era el titular, para siempre.** La titularidad de un vehículo son periodos que la base de datos impide solapar (`EXCLUDE` con `btree_gist`) y congela al cerrarse. El cliente de una orden es el titular al abrirla, y no cambia.
- **El historial manda.** El estado de una orden es una copia del último cambio de su historial, y un trigger diferido lo comprueba al confirmar cada transacción.
- **Lo escrito sin conexión no se pierde ni se duplica.** Los borradores viven en el navegador y se reenvían con un id propio, así que un reenvío tras perder la respuesta no repite la nota.
- **Despliegue desde la CI, con la versión comprobada.** Tras un push a `main` con todo en verde, la CI pide el despliegue a Coolify y comprueba que `/api/v1/meta` responde la versión recién construida.

## Stack

FastAPI · SQLAlchemy async · PostgreSQL 17 (RLS) · SuperTokens · Valkey + SAQ · WeasyPrint · React 19 · TypeScript · Vite · TanStack Query · Tailwind + shadcn/ui · Docker · Coolify

## Arrancarlo

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api python -m app.scripts.create_superadmin <email>
docker compose exec api python -m app.scripts.seed_demo   # opcional: borra todo y carga la demo
```

Frontend en http://localhost:5173, API en http://localhost:8000/docs y correo capturado en http://localhost:8025. Siempre `localhost`, nunca `127.0.0.1`.

## Documentación

```bash
docker compose up docs
```

Y en http://localhost:8001:

- [Especificación de producto](docs/producto/especificacion.md): requisitos numerados, permisos, ciclos de vida y lo que el sistema **no** sabe responder.
- [Arquitectura](docs/arquitectura/index.md): cada decisión con la alternativa descartada, el modelo de datos, las políticas de RLS, los flujos y sus fallos, las pruebas y el orden de construcción.
- Guías: [datos de demostración](docs/guias/demo.md), [versionado](docs/guias/versionado.md) y [despliegue](docs/guias/despliegue.md).
- [Bitácora de decisiones](docs/decisiones/index.md): los cambios de rumbo durante el desarrollo.
