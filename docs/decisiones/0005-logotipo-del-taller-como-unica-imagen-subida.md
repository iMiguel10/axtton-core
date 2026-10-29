# 0005 — El logotipo del taller, la única imagen que se sube

- **Fecha:** 2026-10-29
- **Estado:** aceptada

## Contexto

RF-02 pide que el administrador configure el logotipo del taller, que sale en la cabecera de los presupuestos (RF-37). Pero RF-50 dice que el sistema **no admite ficheros subidos**: todo documento se genera a partir de los datos registrados. Las dos cosas chocan. Las razones de RF-50 siguen en pie: ni almacén de ficheros, ni contenido ajeno dentro de los PDF, ni una puerta para colar algo que el servidor o el navegador interpreten.

## Decisión

Una **excepción acotada a RF-50**, solo para el logotipo, y con condiciones:

- **Solo lo sube el administrador del taller**, y solo hay uno por taller.
- **PNG o JPEG, como mucho 300 KB.** El tamaño se corta al leer el cuerpo de la petición, sin fiarse del `Content-Length`. Se envía tal cual (`PUT /workshop/settings/logo` con su `Content-Type`), sin `multipart`.
- **No se guarda lo subido: se vuelve a dibujar.** Pillow lo decodifica solo con sus decodificadores de PNG y JPEG. El tamaño declarado se comprueba antes de descomprimir (como mucho 4.000 × 4.000 píxeles: una imagen pequeña puede declarar muchos y llenar la memoria). La imagen se reduce a una caja de 800 × 400 y se guarda como un PNG nuevo, sin metadatos. Lo que venga pegado detrás de la imagen, un perfil o un comentario no sobrevive. Decodificar va en un hilo aparte (`infra/images.py`), como el PDF.
- **En la base de datos**, en `workshop_logos` (su clave es el taller, con RLS), y no en `workshops`, que se lee en cada petición. No hay almacén de ficheros.
- **Se usa solo en los documentos generados** (el PDF del presupuesto, paso 7 de F3) y en su pantalla de configuración. El portal no lo enseña, y los correos siguen con la marca de la plataforma.
- **Se audita** cambiarlo y quitarlo.

## Alternativas descartadas

- **Sin logotipo:** el PDF llevaría el nombre del taller en texto. Cumple la norma, pero RF-02 lo pide, y un taller espera ver su marca en un presupuesto.
- **Guardar el fichero subido tal cual:** el PDF incrustaría bytes que nadie ha revisado. Una imagen con algo más dentro (un políglota, un perfil ICC malformado) llegaría a WeasyPrint y al navegador del cliente.
- **Aceptar SVG:** es un documento con scripts y referencias externas. Limpiarlo bien es mucho más difícil que volver a dibujar un mapa de bits.
- **Un almacén de ficheros (disco o S3):** una pieza más que desplegar, que copiar (RNF-33) y que aislar por taller, para una sola imagen pequeña.

## Consecuencias

- **RF-50 tiene una excepción con nombre.** Cualquier otra subida (fotos de la orden, documentos) sigue fuera, y exigiría su propia decisión.
- **Pillow pasa a ser una dependencia directa** (ya venía con WeasyPrint).
- **El logo pesa en la base de datos**, como mucho unos cientos de KB por taller. Con el límite de talleres de una instalación no se nota en las copias.
- **Lo que se ve es lo que guardó el servidor**, no lo que se subió: la pantalla lo enseña tal como saldrá en el PDF.
