# AGENTS.md — NSAC

Toolkit Python para el reto NASA Space Apps 2026 *"Permanent Moon Base
Locations and Mars"*: elegir sitios en Luna/Marte y encontrar sus análogos en
la Tierra. Todo el código, docstrings y comentarios están en **español** —
mantener ese estilo.

## Comandos

```powershell
# Setup (Windows, Python ≥ 3.10)
python -m venv .venv; .\.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONIOENCODING="utf-8"   # imprescindible: acentos en consola Windows

# Verificación (NO hay tests ni CI: la verificación es ejecutar scripts)
python -m nsac.cli doctor                        # 14 fuentes en vivo, sin credenciales
python -m colector_datos.ejemplo_uso --rapido    # fumo del colector (sin GDS, segs)
python -m colector_datos.prueba_funcion --sitio malapert   # informe completo (GDS: minutos)
python -m colector_datos.prueba_dtm --lat 41.2 --lon -23.7 --radio 0.05  # A/B DTM vs LOLA
python -m colector_datos.db_sitios_marte estado  # DB de sitios marcianos
```

Los módulos se ejecutan como `python -m colector_datos.<modulo>` **desde la
raíz** (donde está `pyproject.toml`), no desde dentro del paquete.

## Arquitectura (2 paquetes, roles distintos)

- `nsac/` — capa de acceso a fuentes HTTP (PDS GDS/ODE, USGS STAC, Treks,
  CMR/GIBS, Copernicus, CSA, ASF, EarthCODE, JAXA). `nsac.http` centraliza
  sesión, reintentos y TLS; todos los módulos lo reutilizan.
- `colector_datos/` — **el producto real**: `obtener_datos_sitio(cuerpo, lat,
  lon, radio)` en `api.py` devuelve UN diccionario con secciones fijas
  (`metadatos/topografia/termico/superficie/iluminacion`) para `'luna'`,
  `'marte'` y `'tierra'`, con las MISMAS claves en los tres cuerpos para poder
  compararlos. Todo lo demás existe para alimentar esa función.

Verificación de un cambio: correr `ejemplo_uso`/`prueba_funcion` y comprobar
que el `resumen` del registro (claves y valores) se mantiene — ver
`NOTAS_NOCTURNAS.md` §2.3 como plantilla de comparación frío/tibio.

## Fuentes de verdad

- `colector_datos/NOTAS_NOCTURNAS.md` — bitácora por sesión: mediciones,
  veredictos y decisiones. **Leerla antes de tocar el colector y añadir una
  sección al final de cada sesión de trabajo.** Si los docs contradicen el
  código, gana el código (y actualiza la nota).
- `colector_datos/README.md` — mapa parámetro→módulo→fuente y peculiaridades
  de los datos crudos (LOLA/Diviner).

## Gotchas que rompen consultas (aprendidos a la dura)

- **Convenciones de bbox NO homogéneas**: CMR/STAC usan `(oeste, sur, este,
  norte)`; ODE/GDS `(minlat, maxlat, oeste, este)`; ASF `(sur, oeste, norte,
  este)`. Cada función lo documenta; usar `utilidades.cajas_gds` / `caja_stac`.
- **El GDS de PDS trabaja en longitudes 0-360**: rechaza lon negativas y cajas
  que cruzan el meridiano 0 (`Invalid Lat/Lon Bounding Box`). `cajas_gds` ya
  convierte y parte; no pasar bboxes crudos al GDS.
- **El GDS es LENTO (minutos) y frágil**: `obtener_datos_sitio` recorta el
  radio a ±0.5° (`constantes.RADIO_MAX_GRADOS`) y lanza las llamadas en
  paralelo; el techo frío lo pone Diviner. Si el GDS responde `ResultFiles`
  como string, es error transitorio — `pds.gds_query` lo lanza como
  `RuntimeError` y la caché NO debe guardar esa basura.
- **CRS de otros cuerpos**: PROJ de esta instalación no transforma CRS lunares
  ni marcianas. Kaguya usa `IAU_2015:30100` (grados); los tiles CTX/HiRISE de
  Marte usan `IAU_2015:49910` equirectangular EN METROS, resuelta con la
  fórmula manual (R=3396190, `constantes.RADIO_DATUM_MARTE_M`). Los tiles
  marcianos polares (`stere`) no se pueden leer de forma segura → error claro
  + sin dato puntual, nunca números inventados.
- **Política DTM (en `api.py`, no cambiar a la ligera)**: Luna exige ≥50 %
  píxeles válidos Y ≥90 % de cobertura; si falla cae a GDS LOLA. Marte exige
  solo ≥50 % de cobertura (no hay LOLA de respaldo). En polos lunares el DTM
  Kaguya miente (Malapert: 2 % de píxeles válidos por huecos de sombra).
- **Sufijos DEM**: el asset Kaguya termina en `-dem.tif` y el CTX/HiRISE en
  `_dtm.tif`; el filtro de `topografia_dtm` acepta ambos.
- **Cachés** (`data/` gitignored, sin caducidad — datos históricos):
  `cache_gds.py` (CSV Diviner/LOLA), `cache_catalogo.py` (Treks/STAC), tiles
  DTM en `data/cache/dtm/` y `data/db/sitios_marte.db`. Sitio tibio ≈ 4 s vs
  33-95 s frío. Ruta raíz con `NSAC_DATA_DIR`.
- **Registro de consultas**: `data/registro_sitios.json`, clave
  `cuerpo@lat,lon±radio` — repetir una consulta ACTUALIZA su entrada. El
  `resumen` usa `n_puntos_lola`, que con vía DTM cuenta PÍXELES (nombre
  histórico mantenido por comparabilidad) y lleva `via_topografia`.
- `rasterio` es obligatorio de facto (vía DTM); su ausencia degrada a GDS LOLA
  con mensaje, no rompe. `numpy`/`rasterio` se importan solo dentro de la vía
  DTM; el flujo normal debe seguir funcionando con `pandas` solo.
- Credenciales (solo descargas, no búsquedas): Earthdata, CDSE, JAXA —
  ver `.env.example`. CSA usa certificado Entrust retirado: `nsac.http`
  reintenta sin verificar TLS solo para esos hosts (`NSAC_INSECURE_HOSTS`).

## Git

- Trabajo actual en la rama `dtm-rasterio` (contiene optimización GDS + DTM +
  Marte + DB); `master` está por detrás. Pushear ha dado 403 con la
  credencial de este dispositivo (ver NOTAS §11): Axel empuja desde el suyo.
- Lección repetida de la bitácora: un fix no está hecho hasta que está
  **comiteado** (un fix solo en disco se perdió al sincronizar ramas).

## Estado actual y pendiente principal (NO codificado aún)

**Brecha Tierra vs Luna/Marte:** `obtener_datos_sitio('tierra', ...)` NO
devuelve aún el mismo formato de datos crudos. Luna y Marte devuelven números
reales en cada sección (elevación/pendiente/rugosidad del DTM, temperatura
Diviner, albedo, iluminación); `analogos_tierra.datos_tierra` solo devuelve
CATÁLOGOS (nombres/ids de colecciones CMR, escenas Sentinel-2, capas GIBS) —
ver `colector_datos/analogos_tierra.py`. La ruta de acción acordada (a
verificar antes de codificar):

1. **Topografía (el trozo más barato):** reutilizar la receta de
   `topografia_dtm.analizar_sitio` para `cuerpo='tierra'` — en la Tierra no
   hay problema de CRS (EPSG:4326 estándar, PROJ funciona). DEM candidato:
   Copernicus DEM GLO-30 (abierta en AWS, sin auth) o ASTER/SRTM vía CMR
   (necesita Earthdata Login). Devolver `elevacion_m/pendiente/rugosidad` con
   las mismas claves y `utilidades.estadisticas`.
2. **Térmico:** MODIS LST (MOD11) vía CMR `search_granules` + `earthaccess`
   (auth gratuita), o ERA5; mismo dict que Diviner (media/max/min,
   día/noche). Coste/tiempo a medir antes de decidir.
3. **Superficie:** reflectancia Sentinel-2 (CDSE) o MODIS BRDF; albedo con
   las mismas claves que `superficie.py`.
4. **Iluminación:** cálculo local de geometría solar (igual que Luna/Marte),
   sin llamadas nuevas.
5. **Regla de oro del proyecto:** si una fuente no da el dato, `nota` honesta
   (como hace Marte con THEMIS) — NUNCA inventar números.
6. Verificación: `prueba_tierra.py` comparando claves de `resumen` Tierra vs
   Luna vs Marte, misma plantilla de NOTAS §2.3.
