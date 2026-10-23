# AXTTON CORE

**Gestión para talleres mecánicos, con un portal para que el cliente siga su reparación sin llamar.**

> **Estado: fase de diseño. Todavía no hay código.** Este repositorio contiene, por ahora, la especificación, la arquitectura y el sitio de documentación. El código empieza en F0.

## Qué resuelve

En un taller, la información de cada coche está repartida entre papel, hojas de cálculo, mensajes y llamadas, y el cliente llama varias veces al día para preguntar cómo va. AXTTON CORE junta en un sitio el trabajo diario y resuelve muy bien un flujo concreto:

**se da cita → entra el coche → se diagnostica → se presupuesta → el cliente aprueba desde el móvil → se repara → se entrega**

- **Para el taller:** clientes, vehículos y su historial, citas, órdenes de trabajo, presupuestos con versiones, inventario básico, cobros pendientes y documentos generados (presupuesto, hoja de recepción firmada, resumen de entrega con su garantía).
- **Para el cliente:** un portal privado, sin contraseña (enlace por email), donde ve el estado de su coche, aprueba o rechaza el presupuesto y descarga sus documentos.

No es un programa de facturación, ni de compras, ni de reservas online: la especificación dice qué no es y por qué.

## Decisiones destacadas

- **Multi-taller con el aislamiento en la base de datos.** Cada fila lleva su taller. Las claves foráneas compuestas impiden mezclar datos de dos talleres, y **Row-Level Security** de PostgreSQL impide leerlos aunque una consulta olvide filtrar. Si nadie fija el taller, la consulta no ve nada; nunca ve todo.
- **Tres actores que no se cruzan.** Personal, clientes y superadministrador entran por SuperTokens con recetas distintas, y la API se parte en `/taller`, `/portal` y `/admin`, cada prefijo cerrado a los otros dos desde el router. Una prueba recorre el OpenAPI para que ningún endpoint nuevo se quede fuera.
- **Lo que tiene valor de prueba no se edita.** Un presupuesto enviado, la decisión del cliente y la hoja de recepción firmada se congelan. Lo garantizan los permisos y los triggers de la base de datos, no la disciplina del código.
- **Ajustado a la normativa española de talleres** (RD 1457/1986): validez mínima del presupuesto, renuncia firmada en el resguardo de depósito y garantía de 3 meses o 2.000 km.
- **Avisos que nunca salen dos veces**: se escriben en la misma transacción que el cambio que los provoca, y el envío distingue un fallo seguro (se reintenta) de uno ambiguo (no).

## Stack

FastAPI · SQLAlchemy async · PostgreSQL 17 (RLS) · SuperTokens · Valkey + SAQ · WeasyPrint · React 19 · TypeScript · Vite · TanStack Query · Tailwind + shadcn/ui · Docker · Coolify

## Documentación

```bash
docker compose up docs
```

Y en http://localhost:8001:

- [Especificación de producto](docs/producto/especificacion.md): requisitos numerados, permisos, ciclos de vida y lo que el sistema **no** sabe responder.
- [Arquitectura](docs/arquitectura/index.md): cada decisión con la alternativa descartada, el modelo de datos, las políticas de RLS, los flujos y sus fallos, las pruebas y el orden de construcción.
