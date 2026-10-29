"""Reglas puras de la configuración del taller (RF-02): sin base de datos."""

# El logotipo (decisión 0005). Lo que se sube: como mucho 300 KB, PNG o JPEG.
LOGO_MAX_UPLOAD_BYTES = 300 * 1024
LOGO_ACCEPTED_TYPES = frozenset({"image/png", "image/jpeg"})
# Una imagen de 300 KB puede declarar 20.000 × 20.000 píxeles (comprimida, casi
# no ocupa) y reventar la memoria al descomprimirla: se rechaza antes de leerla.
LOGO_MAX_SOURCE_PIXELS = 4000 * 4000
# Lo que se guarda: reducida a esta caja, que basta para la cabecera de un PDF.
LOGO_MAX_WIDTH = 800
LOGO_MAX_HEIGHT = 400

# Validez del presupuesto en días hábiles (RF-33): 12 es el mínimo legal. El
# máximo no es legal, es para que un error al teclear no deje un presupuesto
# válido durante años.
QUOTE_VALIDITY_MIN_DAYS = 12
QUOTE_VALIDITY_MAX_DAYS = 120

# Tarifas de mano de obra vigentes por taller: un taller tiene unas pocas
# (mecánica, electricidad, chapa); más indica un uso anómalo.
MAX_ACTIVE_LABOR_RATES = 20
