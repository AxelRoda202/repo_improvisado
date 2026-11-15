# colector_datos — un diccionario con todos los parámetros del sitio

Paquete independiente del resto del proyecto que, con **una sola llamada de
función**, devuelve un diccionario de Python con los parámetros del reto,
consultando las fuentes que ya trae el paquete `nsac` (PDS, USGS STAC, Treks,
CMR, Copernicus).

```python
from colector_datos import obtener_datos_sitio

datos = obtener_datos_sitio(cuerpo="luna", lat=-89.9, lon=0.05, radio=0.05)

datos["topografia"]["elevacion_m"]        # {min, max, media, mediana, ...}
datos["termico"]["temperatura_superficial"]
datos["superficie"]["reflectancia_albedo"]
datos["iluminacion"]["zonas_sombra_psr"]
```

## Cómo se mapea cada parámetro (qué archivo lo trae)

| Parámetro pedido | Módulo | Fuente | ¿Cuántas llamadas? |
|---|---|---|---|
| Elevación | `topografia.py` | LOLA por PDS GDS + DTM Kaguya (USGS STAC) | 1 GDS + 1 STAC |
| Pendiente del terreno | `topografia.py` | **calculada en local** desde los mismos puntos LOLA | 0 extra |
| Rugosidad superficial | `topografia.py` | **calculada en local** (desv. típica por celda) | 0 extra |
| Cráteres / formaciones geológicas | `topografia.py` | **calculado en local** (depresiones vs vecinas) + mapa geológico USGS + capas Treks | 0 extra |
| Temperatura media, máx y mín | `termico.py` | Diviner por PDS GDS | 1 GDS |
| Diferencia térmica día/noche | `termico.py` | mismo CSV Diviner (ángulo cenital solar) | 0 extra |
| Variación estacional | `termico.py` | mismo CSV Diviner (agrupando por mes) | 0 extra |
| Tipo de roca | `superficie.py` | heurística sobre el albedo de Diviner | 0 extra |
| Minerales predominantes | `superficie.py` | capas Treks + bundles Clementine (PDS) | 1 PDS |
| Reflectancia y albedo | `termico.py`→`superficie.py` | canales solares 1-2 de Diviner | 0 extra |
| Materiales superficiales y polvo | `superficie.py` | capas Treks (parámetro H / regolito) | 0 extra |
| Horas de iluminación | `iluminacion.py` | capas Treks (LOLA/Kaguya illumination) | 0 extra |
| Energía solar recibida | `iluminacion.py` | cálculo local: E = 1361 W/m² × fracción iluminada | 0 extra |
| Variaciones de exposición solar | `iluminacion.py` | capas Treks + fechas de Diviner | 0 extra |
| Zonas en sombra permanente (PSR) | `iluminacion.py` | capas Treks (PSR) + fracción diurna de Diviner | 0 extra |
| (lado Tierra) | `analogos_tierra.py` | CMR + GIBS + Copernicus | opcional, ~6 |

**Total Luna: ~7 llamadas HTTP** para todo el diccionario (2 son el propio
GDS: consulta + CSV, y pueden tardar minutos).

## Archivos

```
colector_datos/
  __init__.py          expone obtener_datos_sitio()
  api.py               ← la función principal que une todo
  constantes.py        constantes físicas, sitios de ejemplo, palabras clave
  utilidades.py        pendiente, rugosidad, cráteres, distancias, estadísticas
  topografia.py        elevación (LOLA), DTM (USGS STAC), capas Treks
  termico.py           Diviner: temperatura + día/noche + estacional + albedo
  superficie.py        tipo de roca, minerales, polvo/regolito
  iluminacion.py       iluminación, energía solar, PSR
  analogos_tierra.py   el lado terrestre de la comparación (CMR/GIBS/S2)
  ejemplo_uso.py       script de muestra ejecutable
```

## Cómo ejecutar

Desde la raíz del proyecto (donde está `pyproject.toml`):

```powershell
python -m colector_datos.ejemplo_uso              # Shackleton (polo sur lunar)
python -m colector_datos.ejemplo_uso --rapido     # sin GDS (responde en segundos)
python -m colector_datos.ejemplo_uso --marte      # Jezero (Marte)
python -m colector_datos.ejemplo_uso --sitio peary
```

O desde tu propia aplicación:

```python
from colector_datos import obtener_datos_sitio

# Sitio polar lunar, con teselas para el visor y análogos terrestres:
datos = obtener_datos_sitio(
    cuerpo="luna", lat=-89.9, lon=0.05, radio=0.05,
    con_teselas=True,        # URLs WMTS listas para Leaflet/MapLibre (+llamadas)
    incluir_tierra=True,     # sección de datos terrestres (~6 llamadas más)
)
```

## Detalles de diseño (por qué está hecho así)

1. **Menos llamadas, más datos.** El GDS de Diviner devuelve los 9 canales en
   una única consulta (`channel="fffffffff"`): de ese solo CSV salen la
   temperatura (canales 3-9), el albedo (1-2), el día/noche (ángulo solar) y
   la estacionalidad (fecha). Lo mismo con LOLA: una descarga de puntos y
   pendiente/rugosidad/cráteres se calculan en Python, no en la red.
2. **El catálogo de Treks se baja UNA vez** y todos los módulos lo filtran en
   memoria (`utilidades.capas_por_keyword`), sin repetir peticiones.
3. **Una sola llamada STAC** pasa todas las colecciones interesantes a la vez
   (`bbox` compartido).
4. **Aislamiento de fallos:** si una fuente cae, la sección del diccionario
   correspondiente lleva `"error": ...` y el resto sigue funcionando.
5. **Cajas que cruzan el meridiano 0:** `utilidades.cajas_gds` las parte
   automáticamente en dos (el GDS las rechaza si no).
6. **Python básico:** sin numpy ni rasterio para el flujo normal; solo
   `pandas` (ya requerido por `nsac`). Cada función explica en su docstring
   qué hace, qué devuelve y de dónde sale cada número.

## Peculiaridades de los datos crudos (aprendidas a la dura)

- **LOLA (GDS `lolardr`):** cada fila trae 5 detectores (`D1..D5_*`), el radio
  de superficie está en **kilómetros**, los ecos perdidos son `-99`/`999`, y
  hay que NO confundir `SC_radius` (la nave, +50 km) con el radio del suelo.
  La longitud viene en el convenio 0-360 y se normaliza a ±180. Los radios
  descabellados (ruido del láser) se filtran con la desviación absoluta
  mediana (MAD) en `topografia.elevacion_lola`.
- **Diviner (GDS `divinerrdr`):** los 9 canales van como filas (`c`=1..9) y
  la columna `tb` del canal solar NO es temperatura (es la señal reflejada).
  La fecha viene como `01-Dec-2009` y se agrupa por mes del año (1..12) para
  el ciclo estacional lunar (~1 año terrestre). El ángulo cenital solar
  (`csunzen`) separa día (<90°) de noche (>=90°).
- **Polos:** el cálculo de pendiente/rugosidad se hace sobre una proyección
  plana local en metros (`utilidades.proyeccion_local`), porque en los polos
  1° de longitud son apenas unos metros y los cálculos en grados fallan.

## Registro de consultas

Cada llamada a `obtener_datos_sitio()` deja (o actualiza) su entrada en
**`colector_datos/data/registro_sitios.json`** — un JSON con una entrada por
sitio, cuya clave es `cuerpo@lat,lon±radio` (p.ej. `moon@-89.9,0.05±0.05`).
También se registran las consultas de TIERRA (`--cuerpo tierra`). Cada entrada
guarda:

- `fecha_consulta`: cuándo se pidió (repetir la consulta refresca la fecha).
- `resumen`: los números principales con nombre y unidad (elevación media,
  pendiente, temperatura, energía solar...), para hojear la base de sitios.
- `datos_completos`: el diccionario entero de esa consulta (sin la lista
  cruda de puntos LOLA, que queda resumida en `n_puntos`).

La ruta se cambia con la variable de entorno `NSAC_DATA_DIR` (por defecto
`colector_datos/data/`).

## Cuánto tarda cada consulta

- Treks, STAC, PDS Search y el lado Tierra: **segundos**.
- Los CSV crudos del **GDS de PDS** (LOLA/Diviner, solo Luna): **varios
  minutos por consulta**, y el tiempo crece desproporcionadamente con el
  área pedida. Por eso `obtener_datos_sitio()` **recorta el radio a ±0.5°**
  (`constantes.RADIO_MAX_GRADOS`) y lo anota en
  `metadatos.nota_radio`: para más detalle, divide el sitio en sub-cajas.
- Si el servidor responde 502/503, la sesión de `nsac.http` reintenta hasta
  3 veces, lo que puede alargar una consulta lenta todavía más.

## Limitaciones conocidas

- El GDS puede tardar **minutos** por consulta; usa `usar_gds=False` para
  pruebas rápidas (catálogos y capas sin datos puntuales).
- En Marte no existen LOLA/Diviner: la temperatura puntual requiere descargar
  productos THEMIS/TES de PDS ODE (el módulo lo anota y da las capas Treks).
- La detección de cráteres con la nube de puntos LOLA es una **heurística de
  cribado**; para confirmar cráteres usa el DTM del STAC o el mapa geológico.
- `tipo_roca` es una clasificación por umbral de albedo (anortosita/basalto);
  crúzala con las capas de FeO/TiO₂ de Clementine para el informe final.
