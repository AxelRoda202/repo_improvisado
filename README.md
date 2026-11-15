# NSAC — Análogos terrestres de bases lunares y marcianas

Toolkit en Python para el reto de **NASA Space Apps 2026**
*"Identify Earth Locations that Analog the Permanent Moon Base Locations and Mars"*.

El reto pide elegir sitios de base/aterrizaje en la Luna y Marte (topografía,
geología, ambiente, recursos) y encontrar en la Tierra lugares que se les
parezcan — desiertos, regiones polares, terreno volcánico/árido, cuevas — para
usarlos como campo de pruebas. Este repositorio reúne, en un solo paquete, el
acceso **funcional** a todas las fuentes de datos que propone el enunciado.

```
nsac/
  http.py            sesión con reintentos, descargas y fallback TLS
  cli.py             CLI de exploración (doctor + un comando por fuente)
  sources/
    earthdata.py     NASA CMR + GIBS (Earthdata Search / Worldview)
    pds.py           PDS Search, listados HTTP, ODE REST y GDS REST
    usgs_stac.py     STAC de USGS Astrogeology (Luna y Marte)
    copernicus.py    Copernicus Data Space (STAC + OData)
    earthcode.py     ESA Open Science Data Catalogue (EarthCODE)
    csa.py           CSA Canadá: CKAN, datos abiertos RCM y EODMS
    asf.py           Alaska Satellite Facility (SAR)
    trek.py          NASA Solar System Treks (teselas WMTS)
    jaxa.py          JAXA G-Portal / AW3D30 (requiere cuenta)
examples/            4 scripts ejecutables de extremo a extremo
```

## Puesta en marcha

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

$env:PYTHONIOENCODING="utf-8"      # consola de Windows: acentos y símbolos
python -m nsac.cli doctor          # comprueba en vivo las 14 fuentes
```

`doctor` no necesita credenciales: usa los endpoints abiertos. El resultado
esperado es `14/14 fuentes responden` (puede variar si tu red bloquea algún
host o si JAXA no tiene credenciales configuradas).

## Las fuentes, una por una

| Fuente | Módulo | ¿Funciona sin cuenta? | Para qué sirve en el reto |
|---|---|---|---|
| **NASA Earthdata (CMR)** | `earthdata.search_collections`, `search_granules` | Sí (búsqueda) | Catálogo de variables terrestres: LST, humedad, reflectancia, NDVI, elevación |
| **NASA GIBS / Worldview** | `earthdata.gibs_tile_url`, `search_gibs_layers` | Sí | Teselas XYZ listas para Leaflet/MapLibre; las mismas capas de Worldview |
| **PDS Search API** | `pds.search_bundles`, `members`, `bundle_collections` | Sí | Archivo planetario PDS4: bundles y colecciones de LRO, MRO, etc. |
| **PDS listados HTTP** | `pds.list_dir` | Sí | Descarga directa de productos en `pds-geosciences.wustl.edu` |
| **PDS ODE REST** | `pds.ode_products`, `ode_iipt` | Sí | Metadatos de productos LRO/MRO por bbox y fecha |
| **PDS GDS REST** | `pds.gds_query`, `gds_extract_points` | Sí | **Datos ya tabulados** (LOLA, Diviner) por bbox: la vía más rápida para analizar |
| **USGS Astrogeology STAC** | `usgs_stac.search`, `best_asset` | Sí | La mejor puerta a Luna y Marte: DTM de Kaguya TC, HiRISE, CTX, THEMIS |
| **Copernicus Data Space** | `copernicus.search_stac`, `odata_products` | Búsqueda sí; **descarga con cuenta gratuita** | Sentinel-1/2/3 para el sitio terrestre (óptico + SAR) |
| **ESA EarthCODE** | `earthcode.collections`, `search` | Sí | Productos ambientales ESA para caracterizar el análogo |
| **CSA (Canadá)** | `csa.ckan_search`, `rcm_regions`, `rcm_scenes`, `eodms_collections` | Sí | RCM/RADARSAT: SAR abierto del Ártico y la Antártida (análogos polares) |
| **ASF** | `asf.search` | Búsqueda sí; descarga con Earthdata Login | SAR Sentinel-1/RADARSAT-2 para rugosidad y humedad |
| **NASA Solar System Treks** | `trek.layers`, `find_layers`, `tile_url` | Sí | Capas **ya renderizadas** de Luna/Marte (DEM, pendiente, PSR, mosaicos) |
| **JAXA G-Portal / AW3D30** | `jaxa.aw3d30_tile`, `gportal_search` | **No**: cuenta obligatoria | MDE global 30 m; alternativa sin registro: Kaguya TC en USGS STAC |

### Avisos importantes

- **CMR es solo Tierra.** Para Luna y Marte usa `pds`, `usgs_stac` o `trek`.
- **Descargas autenticadas.** Earthdata, CDSE, ASF y JAXA necesitan cuenta
  gratuita y token; ver `.env.example`. La búsqueda y los metadatos funcionan
  sin credenciales.
- **CSA y TLS.** El portal de datos de la CSA usa un certificado de Entrust,
  cuyas CA se retiraron de los almacenes de confianza en 2025. `nsac.http`
  reintenta sin verificar TLS **solo** para esos hosts y avisa por consola. Se
  controla con `NSAC_INSECURE_HOSTS` y `NSAC_VERIFY_SSL`.
- **PDS Search API.** El parámetro `keywords` no filtra de forma fiable y
  `sort=id` provoca error 500. Por eso `search_bundles()` pide todos los
  bundles (~900) y filtra en local. HiRISE/CTX no están en el registro.
- **ODE REST.** Exige combinaciones exactas `(target, host, instrumento,
  producto)`: `LRO/LOLA/RDR4` existe, `LRO/LOLA/RDR` no. Usa `ode_iipt()`.
- **GDS REST.** Devuelve CSV si el área es pequeña y `.tab` (sin cabecera) si
  es grande; las columnas se recuperan del comentario del propio archivo.
  Rechaza las cajas que cruzan el meridiano 0 (`Invalid Lat/Lon Bounding Box`),
  así que pide longitudes dentro de un mismo hemisferio o 0-360.

## CLI

```powershell
python -m nsac.cli doctor

python -m nsac.cli earth search --keyword "land surface temperature"
python -m nsac.cli earth gibs --keyword "TrueColor"

python -m nsac.cli pds bundles --keyword diviner
python -m nsac.cli pds dir

python -m nsac.cli moon ode --iid LOLA --pt RDR4 --bbox -90,-85,-180,180
python -m nsac.cli moon gds --query divinerrdr --bbox -89.6,-89,0,1
python -m nsac.cli moon iipt --filter LRO

python -m nsac.cli stac --list
python -m nsac.cli stac --collection kaguya_terrain_camera_usgs_dtms_v2_southpolar --bbox 0,-89.7,1.5,-89.2

python -m nsac.cli trek layers --body moon --keyword PSR
python -m nsac.cli trek tile --layer LOLA_DEM --zoom 2 --row 0 --col 0

python -m nsac.cli csa regions
python -m nsac.cli csa scenes --region "Canadian Arctic"
python -m nsac.cli copernicus --collection sentinel-2-l1c --bbox -70.5,-25.5,-68.5,-23.0
python -m nsac.cli asf --platform Sentinel-1 --bbox -25.5,-70.5,-23.0,-68.5
python -m nsac.cli earthcode
```

## Ejemplos ejecutables

| Script | Qué demuestra |
|---|---|
| `examples/01_analogos_tierra.py` | Catálogo de variables en CMR, teselas GIBS y tabla de 7 sitios análogos con su justificación |
| `examples/02_luna_polo_sur.py` | Temperatura Diviner + elevación LOLA (GDS) y DTM Kaguya del polo sur (USGS STAC) |
| `examples/03_marte_sitios.py` | DTM de HiRISE/CTX en Jezero, capas de Mars Trek y bundles MRO |
| `examples/04_sar_rcm.py` | Escenas RCM abiertas del Ártico y búsqueda Sentinel-1 en ASF (`--download` baja la primera) |

```powershell
python examples/01_analogos_tierra.py
python examples/02_luna_polo_sur.py
python examples/03_marte_sitios.py
python examples/04_sar_rcm.py
```

## Cómo usarlo en la aplicación

Arquitectura mínima que cubre el enunciado:

1. **Definir el sitio lunar/marciano** con `pds.ode_products` y
   `usgs_stac.search` sobre los presets de `dtm_presets()` (polos lunares,
   Jezero, etc.).
2. **Extraer criterios** (elevación, pendiente, temperatura, iluminación,
   rugosidad) con GDS, STAC y las capas de `trek`.
3. **Buscar candidatos terrestres** con `earthdata` (variables), `copernicus`
   (óptico), `csa`/`asf` (SAR) y `earthcode` (ambiente).
4. **Puntuar la similitud** por criterio y pintar el resultado con teselas
   GIBS (Tierra) y Treks (Luna/Marte) en un visor Leaflet o MapLibre.

Criterios de analogía recomendados, alineados con el enunciado:

| Criterio | Luna | Marte | Dato terrestre |
|---|---|---|---|
| Topografía | pendiente, rugosidad | valles, cráteres | SRTM / Copernicus DEM |
| Geología | regolito, basalto | sulfatos, arcillas | reflectancia MODIS/Sentinel-2 |
| Ambiente | PSR, frío extremo | desierto hiperárido | LST MODIS, ERA5 |
| Recursos | hielo en PSR | hielo subsuperficial | SMAP, SAR (RCM/Sentinel-1) |

## Requisitos

- Python ≥ 3.10
- `requests`, `pandas` (obligatorios)
- Opcionales en `requirements.txt`: `rasterio`, `rioxarray`, `pystac-client`
  (ráster/STAC), `matplotlib`, `folium` (visualización), `earthaccess`,
  `python-dotenv` (descargas autenticadas).

## Notas de implementación

- `nsac.http` centraliza la sesión, los reintentos (429/5xx) y las descargas en
  streaming; todos los módulos lo reutilizan.
- Los bbox no son homogéneos entre APIs: CMR/STAC usan
  `(oeste, sur, este, norte)`, ODE/GDS usan `(minlat, maxlat, oeste, este)` y
  ASF usa `(sur, oeste, norte, este)`. Cada función lo documenta en su
  docstring.
- `usgs_stac.best_asset(item)` elige el raster/3D útil de cada colección
  (`dtm`, `image`, `data`=COPC-LAZ...) sin tener que conocer el esquema.
