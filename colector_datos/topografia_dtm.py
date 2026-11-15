"""topografia_dtm.py — EXPERIMENTO A (rama `dtm-rasterio`): topografía desde
el DTM de Kaguya (GeoTIFF) en vez de la nube de puntos de LOLA (GDS).

POR QUÉ: el GDS tarda minutos porque el servidor fabrica el CSV a mano alzada
punto por punto. Los DTMs de Kaguya Terrain Camera (USGS Astrogeology) son
GeoTIFFs de ~7 MB en un S3 estático: se descargan en segundos y la lectura es
un trozo de matriz (window read), no una consulta pesada. Resolución ~10 m/px,
muy superior a la separación típica de los puntos LOLA crudos.

QUÉ CALCULA (misma familia de métricas que la vía GDS, para poder comparar):
  - elevación: mín/media/mediana/máx/desv. típica
  - pendiente: gradiente local en grados (con distancia real en metros,
    corregida por la latitud si el raster es geográfico)
  - rugosidad: desv. típica dentro de celdas de ~100 m (misma definición que
    `utilidades.pendiente_y_rugosidad` usa sobre la nube de puntos)
  - cobertura: cuánto de la caja pedida queda dentro del tile (los tiles de
    Kaguya son cuadrantes; una caja grande puede necesitar más de uno)

FALLBACK: si no hay tile DEM (`.tif`) que cubra el sitio, se devuelve un dict
con `fallback="lolardr"` y `api.py` (cuando esto se integre) usaría la vía
GDS de siempre. Este módulo NO sustituye a `topografia.py`: es un piloto.

Solo se toca la red 2 veces: 1 POST al STAC (metadatos) + 1 GET del TIFF.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import constantes, topografia

# Radio lunar medio (IAU): para convertir arco en superficie en metros.
RADIO_LUNA_M = 1_737_400.0

# Carpeta donde se guardan los TIFFs descargados (el .gitignore excluye
# data/, y los tiles se reutilizan como la caché del GDS: son históricos).
CARPETA_TILES = Path(constantes.RUTA_REGISTRO).parent / "cache" / "dtm"


def _tile_dem_para(bbox_stac: tuple, lat: float) -> dict[str, Any] | None:
    """Del catálogo STAC, elige el tile DEM (GeoTIFF) que cubra el CENTRO.

    `dtm_disponibles` ya habla con el STAC y trae `url_mejor_asset` por item;
    aquí solo filtramos los que son TIFF de elevación (los items de LOLA
    apuntan a nubes de puntos `.copc.laz`, que pesan 100+ MB: descartados).
    Si hay varios, gana el que contenga el centro de la caja.
    """
    from nsac.sources import usgs_stac  # solo para reusar la sesión HTTP

    items = topografia.dtm_disponibles("moon", bbox_stac, lat)
    tifs = [it for it in items
            if str(it.get("url_mejor_asset", "")).lower().endswith("-dem.tif")]
    if not tifs:
        return None
    return tifs[0]  # por ahora: 1 tile (ver 'cobertura' en el informe)


def _metros_por_pixel(transform, crs, lat_centro: float) -> tuple[float, float]:
    """Tamaño REAL en metros de un píxel del raster (dx, dy).

    Si el CRS es proyectado (p.ej. estereográfico polar), el transform ya va
    en metros. Si es geográfico (grados), hay que multiplicar por el radio
    lunar y el coseno de la latitud (los meridianos se juntan hacia el polo).
    Se calcula con la propia librería: transformamos 2 puntos vecinos a
    lon/lat y medimos el arco con la fórmula del haversine.
    """
    import numpy as np
    import rasterio.warp

    if crs is not None and not crs.is_geographic:
        return abs(transform.a), abs(transform.e)

    # Raster geográfico: distancia real de 1 píxel en metros.
    # - vertical: arco por grado * grados de píxel (no depende de la latitud)
    # - horizontal: lo mismo multiplicado por cos(lat) (los meridianos se
    #   van juntando hacia el polo)
    import numpy as np

    dx_grados = abs(transform.a)
    dy_grados = abs(transform.e)
    arc_por_grado = 3.141592653589793 * RADIO_LUNA_M / 180.0
    dx_m = dx_grados * arc_por_grado * np.cos(np.radians(lat_centro))
    dy_m = dy_grados * arc_por_grado
    return float(dx_m), float(dy_m)


def analizar_sitio(lat: float, lon: float, radio: float,
                   aviso=None) -> dict[str, Any]:
    """Piloto completo del experimento A para UN sitio lunar.

    Pasos (cronometrados por separado):
      1. STAC: buscar el tile Kaguya TC DEM que cubre la caja.
      2. Descarga: bajar el GeoTIFF (~7 MB) a data/cache/dtm/ (si ya estaba,
         se salta la red).
      3. Cómputo: window read del trozo que interesa + pendiente + rugosidad.

    Devuelve un dict con métricas + metadatos + tiempos + cobertura. NUNCA
    lanza: ante cualquier fallo devuelve {'error': ..., 'fallback': 'lolardr'}
    para que la integración futura sepa que debe usar la vía GDS.
    """
    import numpy as np

    def _aviso(msg: str) -> None:
        if aviso:
            aviso(msg)

    out: dict[str, Any] = {"fuente": "Kaguya TC DTM (USGS STAC) vía rasterio"}
    try:
        # --- caja en el convenio STAC (-180..180) -------------------------
        oeste = lon - radio
        este = lon + radio
        sur = max(-90.0, lat - radio)
        norte = min(90.0, lat + radio)
        bbox_stac = (oeste, sur, este, norte)

        # --- 1) STAC -------------------------------------------------------
        t0 = time.perf_counter()
        tile = _tile_dem_para(bbox_stac, lat)
        out["stac_s"] = round(time.perf_counter() - t0, 1)
        if tile is None:
            out["error"] = "sin tile Kaguya DEM (tif) que cubra la caja"
            out["fallback"] = "lolardr"
            return out
        out["tile"] = tile.get("id")
        out["url"] = tile.get("url_mejor_asset")

        # --- 2) descarga (con reutilización local) -------------------------
        CARPETA_TILES.mkdir(parents=True, exist_ok=True)
        ruta_tif = CARPETA_TILES / (f"{tile.get('id')}.tif")
        if ruta_tif.exists():
            _aviso(f"tile ya en disco: {ruta_tif.name}")
            out["descarga_s"] = 0.0
            out["de_cache"] = True
        else:
            from nsac import http
            _aviso(f"bajando tile Kaguya DEM ({tile.get('id')})...")
            t0 = time.perf_counter()
            http.download(tile["url_mejor_asset"], ruta_tif)
            out["descarga_s"] = round(time.perf_counter() - t0, 1)
            out["de_cache"] = False

        # --- 3) window read + métricas ------------------------------------
        import rasterio
        from rasterio.windows import from_bounds

        t0 = time.perf_counter()
        with rasterio.open(ruta_tif) as src:
            # Los tiles de la Luna usan CRS IAU (p.ej. 'Moon (2015) -
            # Sphere / Ocentric / Equirectangular, clon = 180'), NO el
            # EPSG:4326 terrestre. OJO: EPSG:4326 significa LA TIERRA y
            # PROJ se niega a convertir Tierra<->Luna. La CRS de origen
            # correcta es la geográfica LUNAR, IAU_2015:30100.
            # Resaldo con la fórmula manual de la equirectangular por si
            # una instalación de PROJ no trae la base IAU.
            import rasterio.warp
            try:
                xs, ys = rasterio.warp.transform(
                    "IAU_2015:30100", src.crs, [oeste, este], [sur, norte])
            except Exception:
                # Equirectangular esférica: x = R·(λ-λ0)·cos(φ1) [radianes],
                # y = R·φ. Vale para los tiles ecuatoriales; los polares
                # (estereográficos) caerían al fallback GDS.
                import math
                conv = src.crs.to_dict()
                clon = float(conv.get("central_meridian", 0.0) or 0.0)
                phi1 = float(conv.get("standard_parallel", 0.0) or 0.0)
                R = RADIO_LUNA_M

                def _x(lon_v: float) -> float:
                    rel = ((lon_v - clon + 180.0) % 360.0) - 180.0
                    return (R * math.radians(rel)
                            * math.cos(math.radians(phi1)))

                def _y(lat_v: float) -> float:
                    return R * math.radians(lat_v)

                xs = [_x(oeste), _x(este)]
                ys = [_y(sur), _y(norte)]
            izquierda, derecha = min(xs), max(xs)
            abajo, arriba = min(ys), max(ys)

            # Cobertura: qué fracción de la caja cae dentro del tile.
            b = src.bounds
            ancho_caja = derecha - izquierda
            alto_caja = arriba - abajo
            inter_x = max(0.0, min(derecha, b.right) - max(izquierda, b.left))
            inter_y = max(0.0, min(arriba, b.top) - max(abajo, b.bottom))
            out["cobertura_fraccion"] = round(
                (inter_x * inter_y) / max(ancho_caja * alto_caja, 1e-12), 3)

            # Window read: SOLO el trozo del raster que cubre la caja
            # (recortado a lo que el tile tenga; el resto es 'cobertura').
            win = from_bounds(max(izquierda, b.left), max(abajo, b.bottom),
                              min(derecha, b.right), min(arriba, b.top),
                              transform=src.transform)
            z = src.read(1, window=win).astype("float64")
            z_transform = src.transform  # ojo: es la del raster entero
            crs = src.crs
            res_px = (src.res[0], src.res[1])
            nodata = src.nodata

        # Nodata (Kaguya usa -32767 u otros centinelas): fuera. En los
        # tiles POLARES hay huecos GRANDES (zonas en sombra sin imagen TC):
        # por eso se reporta la fracción de píxeles válidos, para que el
        # llamador sepa si las métricas describen la caja entera o un trozo.
        if nodata is not None:
            z[z == nodata] = np.nan
        z[z < -1e5] = np.nan  # centinela genérico por si acaso
        validos = int(np.isfinite(z).sum())
        if validos < 25:
            out["error"] = "el trozo leído casi no tiene píxeles válidos"
            out["fallback"] = "lolardr"
            return out
        out["pixeles_validos_fraccion"] = round(
            validos / max(z.size, 1), 3)

        # POLÍTICA DE FIABILIDAD: si menos de la mitad de la caja tiene
        # píxeles reales (típico en tiles polares, huecos por sombra),
        # las métricas describen un trozo, no el sitio. `api.py`, al
        # integrar esto, debería caer al fallback LOLA en ese caso.
        out["confiable"] = out["pixeles_validos_fraccion"] >= 0.5

        dx_m, dy_m = _metros_por_pixel(z_transform, crs, lat)
        out["resolucion_m"] = round((dx_m + dy_m) / 2.0, 1)

        # Elevación (m sobre el radio de referencia lunar).
        out["elevacion"] = {
            "n_pixeles": validos,
            "min": round(float(np.nanmin(z)), 3),
            "media": round(float(np.nanmean(z)), 3),
            "mediana": round(float(np.nanmedian(z)), 3),
            "max": round(float(np.nanmax(z)), 3),
            "std": round(float(np.nanstd(z)), 3),
        }

        # Pendiente: gradiente por diferencia finita con distancia real.
        gy, gx = np.gradient(z, dy_m, dx_m)
        pend = np.degrees(np.arctan(np.hypot(gx, gy)))
        pend = pend[np.isfinite(pend) & np.isfinite(z)]
        out["pendiente"] = {
            "n_pixeles": int(pend.size),
            "media": round(float(pend.mean()), 3),
            "mediana": round(float(np.median(pend)), 3),
            "max": round(float(pend.max()), 3),
        }

        # Rugosidad: std de la altura dentro de celdas de ~100 m (misma
        # definición que la vía GDS -> comparable directamente).
        paso = max(1, int(round(100.0 / max(dx_m, 1e-6))))
        h = (z.shape[0] // paso) * paso
        w = (z.shape[1] // paso) * paso
        if h >= paso and w >= paso:
            bloques = z[:h, :w].reshape(h // paso, paso, w // paso, paso)
            # Un bloque entero en sombra (todo NaN) dispara un aviso de
            # numpy ('Degrees of freedom <= 0'): es esperable, se calla.
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rug_celda = np.nanstd(bloques, axis=(1, 3))
            rug = rug_celda[np.isfinite(rug_celda)]
            out["rugosidad"] = {
                "n_celdas_100m": int(rug.size),
                "media": round(float(rug.mean()), 3),
                "mediana": round(float(np.median(rug)), 3),
                "max": round(float(rug.max()), 3),
                "tamano_celda_m": paso * dx_m,
            }
        else:
            out["rugosidad"] = {"nota": "caja más pequeña que una celda de 100 m"}

        out["computo_s"] = round(time.perf_counter() - t0, 1)
        out["total_s"] = round(
            out["stac_s"] + out["descarga_s"] + out["computo_s"], 1)
    except Exception as exc:
        out["error"] = str(exc)
        out["fallback"] = "lolardr"
    return out
