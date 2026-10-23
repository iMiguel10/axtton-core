# Bitácora de decisiones

Registro de las decisiones tomadas **durante el desarrollo**. Las fundacionales están en la [tabla de decisiones de la arquitectura](../arquitectura/index.md#1-decisiones) (A1–A14) y en las [decisiones tomadas de la especificación](../producto/especificacion.md#2-decisiones-tomadas).

Se registra una entrada cuando cambia algo ya documentado, cuando se eligió entre alternativas reales y la descartada era defendible, o cuando alguien preguntaría dentro de seis meses por qué se hizo así. No merece entrada nada cuya respuesta sea "porque es lo normal".

Ficheros con el formato `NNNN-titulo-corto.md`, añadidos también a la navegación de `mkdocs.yml`.

Todavía no hay entradas: el proyecto está en fase de diseño.

## Plantilla

```markdown
# NNNN — Título de la decisión

- **Fecha:** AAAA-MM-DD
- **Estado:** propuesta | aceptada | sustituida por [NNNN](NNNN-....md)

## Contexto
Qué situación obligó a decidir. Sin esto, la decisión parecerá arbitraria dentro de un año.

## Decisión
Qué se hizo, en una o dos frases.

## Alternativas descartadas
Cada una con el motivo real del descarte.

## Consecuencias
Qué se gana, qué se pierde, qué queda pendiente de vigilar.
```
