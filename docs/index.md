# AXTTON CORE

Sistema de gestión para talleres mecánicos: centraliza clientes, vehículos, citas, órdenes de trabajo, presupuestos, inventario y documentos, y da al cliente un portal privado donde seguir la reparación y aprobar el presupuesto sin llamar al taller.

!!! warning "Estado"
    F0 y F1 hechas y cerradas ([lo aprendido en F0](arquitectura/f0-cierre.md), [en F1](arquitectura/f1-cierre.md)): autenticación, talleres, personal, auditoría y aislamiento completo. Siguiente fase: F2, el núcleo operativo. La [especificación](producto/especificacion.md) y la [arquitectura](arquitectura/index.md) son la referencia del diseño.

## En una página

| | |
|---|---|
| **Qué resuelve** | Que la información del taller no esté repartida entre papel, hojas de cálculo, mensajes y llamadas, y que el cliente sepa cómo va su coche sin preguntar |
| **Para quién** | Talleres mecánicos (administradores y mecánicos) y sus clientes; una instalación sirve a muchos talleres o a uno solo |
| **Stack** | FastAPI · SQLAlchemy async · PostgreSQL 17 con RLS · SuperTokens · Valkey + SAQ · WeasyPrint · React 19 · TypeScript · Vite · Docker |
| **Técnica** | Monolito en capas, aislamiento entre talleres en tres capas (aplicación, FK compuestas y RLS), tres actores con prefijos de API separados, historiales append-only y presupuestos inmutables una vez enviados |
| **Naturaleza** | Portfolio serio: rigor en el núcleo técnico, lo comercial pospuesto `[C]` |

## Por dónde empezar

- [Especificación](producto/especificacion.md): qué hace el producto, sus requisitos numerados, el ciclo de vida de una orden de trabajo y lo que **no** sabe responder.
- [Arquitectura](arquitectura/index.md): decisiones con sus alternativas descartadas, autenticación de tres actores, modelo de datos y RLS, flujos, segundo plano, pruebas, orden de implementación y riesgos.
- [Cierre de F0](arquitectura/f0-cierre.md): lo que enseñó el esqueleto y qué se queda.
- [Decisiones](decisiones/index.md): la bitácora de cambios de rumbo durante el desarrollo.

## Las tres ideas que sostienen el diseño

1. **Nada es de otro taller, y la base de datos lo garantiza.** Cada fila lleva su taller; las claves foráneas compuestas impiden enlazar datos de dos talleres, y Row-Level Security impide leerlos aunque una consulta olvide filtrar. Un olvido falla cerrado: no ve nada, nunca todo.
2. **Lo que tiene valor de prueba no se toca.** Un presupuesto enviado, una decisión del cliente, una hoja de recepción firmada y el historial de estados y de stock no se editan: se corrigen con una versión nueva o un movimiento contrario. Lo garantizan los permisos y los triggers de la base de datos, no la disciplina del código.
3. **El sistema solo sabe lo que el taller registra, y lo dice.** El portal enseña cuándo se actualizó cada orden y avisa cuando una fecha prevista ya pasó; el stock es lo registrado, no lo que hay en la estantería; el cobro no es contabilidad.

## Cómo se mantiene esta documentación

- La fuente vive en `docs/` junto al código y **cambia en el mismo commit** que el código que describe.
- Los diagramas son texto (Mermaid), no imágenes.
- La referencia de la API no se escribe a mano: se genera del contrato OpenAPI.
- `guias/` y `referencia/` están vacías a propósito: se llenan cuando exista el código que describen.
- Si el código y un documento no coinciden, no se corrige el documento sin más: primero se averigua si el diseño evolucionó o si la implementación se lo saltó.
