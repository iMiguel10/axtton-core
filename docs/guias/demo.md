# Datos de demostración

`app/scripts/seed_demo.py` vacía la base de datos y la llena con dos talleres de ejemplo, su personal y un mes de trabajo. Sirve para probar la aplicación entera en desarrollo y para la demo desplegada, que lo ejecuta cada noche para que cada visitante empiece desde el mismo punto.

!!! danger "Borra todos los datos"
    Solo corre con `DEMO_SEED_ENABLED=true`. Una instalación de verdad no tiene esa variable y el script se niega a empezar.

## Cómo se ejecuta

```bash
docker compose exec -e DEMO_SEED_ENABLED=true api python -m app.scripts.seed_demo
```

O con `DEMO_SEED_ENABLED=true` en tu `.env` (el de `.env.example` la trae activada para desarrollo) y sin el `-e`. Se puede repetir cuantas veces haga falta.

En la demo desplegada, cada noche y con una opción más:

```bash
python -m app.scripts.seed_demo --purge-other-accounts
```

`--purge-other-accounts` borra de SuperTokens todas las cuentas que no son de la demo: las que crean los visitantes al aceptar invitaciones. **No lo uses en desarrollo**: borraría tus cuentas de prueba.

## Cuentas

Todas con la misma contraseña, `demo-axtton-2026` (o la de `DEMO_PASSWORD`, si está definida). Es pública a propósito: es la de la demo.

| Email | Quién es | Qué ve |
|---|---|---|
| `superadmin@demo.example.com` | Superadministrador | `/admin`: los dos talleres, sus límites, la auditoría de plataforma |
| `laura@demo.example.com` | Laura Martínez, administradora de **los dos talleres** | Todo, y el selector de talleres |
| `javier@demo.example.com` | Javier Ruiz, mecánico (Talleres Martínez) | Lo del mecánico: sus órdenes, diagnóstico, trabajos, notas |
| `sergio@demo.example.com` | Sergio Gómez, mecánico (Talleres Martínez) | Igual que Javier |
| `marta@demo.example.com` | Marta Soler, mecánica (Taller Rápido Levante) | El taller pequeño |

Pedro Ortega, aprendiz, tiene ficha pero no acceso: otros anotan su trabajo (RF-23).

Los talleres de la demo tienen **límites más bajos** que el plan básico (`DEMO_PLAN` en `domain/limits.py`): 200 clientes, 300 vehículos y 100 órdenes al mes. Bastan para probarlo todo y no dejan llenar la base de datos en el día que pasa entre reinicio y reinicio.

## Qué hay

**Talleres Martínez** (Albacete) tiene doce clientes, particulares y empresas, y doce vehículos con años de historial. Sus órdenes cubren todo lo que se puede hacer sin presupuestos (llegan en F3):

- una recibida hoy y otra en diagnóstico **parada desde hace cinco días**;
- en reparación sin presupuesto, por precio cerrado o por garantía (RF-27), una de ellas **de garantía enlazada** a una reparación anterior;
- esperando piezas, con un trabajo anotado por error y **anulado**;
- lista para recoger, y lista **sin reparar** (el diagnóstico no encontró nada);
- entregadas **pendientes de cobro** desde hace 19 y 3 días (RF-29), cobradas en efectivo, con tarjeta y por transferencia, y una **sin cargo**;
- una cancelada;
- diagnósticos con varias versiones, notas internas y trabajos de varios mecánicos;
- un vehículo que **cambió de titular** hace un mes (RF-12);
- una clienta **anonimizada** a petición suya (RF-15), con su orden conservada, y un cliente archivado.

**Taller Rápido Levante** (Valencia) es pequeño, con dos clientes y dos órdenes: sirve para ver el cambio de taller.

## Cómo está hecho

- Los datos del taller se crean con **los services de verdad**, en transacciones del taller con RLS. Cumplen todas las reglas: el historial de estados, la numeración, los permisos de cada rol y la auditoría. Si una regla cambia y la demo deja de cumplirla, el script falla (y su prueba, `test_seed_demo.py`).
- Como todo se crea "ahora", al final **las fechas se mueven hacia atrás**, relativas a hoy: la demo nunca envejece. Lo hacen el rol de plataforma (órdenes, historiales, clientes, vehículos) y el dueño para los periodos de titularidad, cuyo trigger los congela con cualquier rol. El dueño lo desactiva dentro de su transacción y lo vuelve a activar antes de confirmar.
- Después se **renumeran** las órdenes por fecha, con el año en la zona del taller, y se rehacen los contadores: la siguiente orden sigue la serie.
- **La auditoría se queda con la hora real** en que corrió el script: es append-only también para esto.
- Las cuentas de SuperTokens sobreviven al vaciado (su base de datos es otra): se reutilizan, se les vuelve a poner la contraseña y se cierran sus sesiones.
