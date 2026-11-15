"""topografia_dtm.py — EXPERIMENTO A (rama `dtm-rasterio`): topografía desde
el DTM de Kaguya (GeoTIFF) en vez de la nube de puntos de LOLA (GDS).

POR QUÉ: el GDS tarda minutos porque el servidor fabrica el CSV a mano alzada
punto por punto. Los DTMs de Kaguya Terrain Camera (USGS Astrogeology) son
GeoTIFFs de ~7 MB en un S3 estático: se descargan en segundos y la lectura es
un trozo de matriz (window read), no una consulta pesada. Resolución real
19-30 m/px (según el tile), muy superior a la separación típica de los puntos
LOLA crudos.

QUÉ CALCULA (mismas métricas que la vía GDS, en el MISMO formato, para poder
comparar y para que `api.py` las enchufe sin adaptación):
  - elevación: {n, min, media, mediana, max, desv_estandar} (m sobre datum)
  - pendiente: idem, por gradiente local con distancia real en metros
  - rugosidad: idem, desv. típica dentro de celdas de ~100 m (misma
    definición que `utilidades.pendiente_y_rugosidad` usa sobre la nube)
  - cráteres: depresiones de >sigma·σ respecto a sus vecinas sobre celdas
    de ~200 m (misma heurística que `utilidades.detectar_crateres` pero
    sobre la malla regular del DTM, sin nube de puntos)
  - cobertura: fracción de la caja dentro del tile y fracción de píxeles
    válidos (los tiles POLARES tienen huecos enormes por sombra: medido en
    Malapert, solo 2 % de píxeles útiles → ahí NO hay que fiarse del DTM)

FALLBACK: si no hay tile DEM que cubra la caja, si los píxeles válidos son
menos de la mitad o si `rasterio` no está instalado, se devuelve un dict con
`fallback="lolardr"` y `api.py` usa la vía GDS de siempre. Este módulo y
`topografia.py` conviven: no se sustituye a LOLA a la fuerza, se elige por
calidad de cobertura.

Solo se toca la red 2 veces: 1 POST al STAC (metadatos, cacheado) + 1 GET
del TIFF (guardado en data/cache/dtm/, datos históricos como la caché GDS).
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


def _a_estadisticas(n: int, vmin: float, media: float, mediana: float,
                    vmax: float, desv: float) -> dict[str, Any]:
    """Mismo formato que `utilidades.estadisticas`, a partir de numpy.

    `api.py` y el informe (`prueba_funcion.py`) consumen esta forma de dict
    para elevación/pendiente/rugosidad; con esto la vía DTM y la vía LOLA
    son intercambiables para todos los consumidores.
    """
    r = lambda v: round(float(v), 3)
    return {
        "n": int(n),
        "min": r(vmin),
        "max": r(vmax),
        "media": r(media),
        "mediana": r(mediana),
        "desv_estandar": r(desv),
    }


def _tile_dem_para(bbox_stac: tuple, lat: float, lon: float,
                   items: list[dict] | None = None) -> dict[str, Any] | None:
    """Del catálogo STAC, elige el tile DEM (GeoTIFF) que cubra la caja.

    `dtm_disponibles` ya habla con el STAC (y ahora lo cachea); si el
    llamador trae esos items (`items`), se reutilizan y no se repite la
    llamada. Filtramos los que son TIFF de elevación (los items de LOLA
    apuntan a nubes `.copc.laz` de 100+ MB: descartados).

    Con bbox en los items, gana el tile que CONTIENE el centro de la caja;
    si ninguno lo contiene, el de mayor solape con la caja. Sin bbox
    (formato antiguo), cae al primer tif como antes.
    """
    if items is None:
        items = topografia.dtm_disponibles("moon", bbox_stac, lat)

    tifs = [it for it in items
            if str(it.get("url_mejor_asset", "")).lower().endswith("-dem.tif")]
    if not tifs:
        return None

    con_bbox = [it for it in tifs
                if isinstance(it.get("bbox"), (list, tuple)) and len(it["bbox"]) >= 4]
    if not con_bbox:
        return tifs[0]  # sin bbox: no hay nada mejor que elegir

    def _solape(it) -> float:
        w, s, e, n = it["bbox"][:4]
        ix = max(0.0, min(e, bbox_stac[2]) - max(w, bbox_stac[0]))
        iy = max(0.0, min(n, bbox_stac[3]) - max(s, bbox_stac[1]))
        return ix * iy

    # 1º: tile que contenga el centro; 2º: el de mayor solape con la caja.
    for it in con_bbox:
        w, s, e, n = it["bbox"][:4]
        if w <= lon <= e and s <= lat <= n:
            return it
    return max(con_bbox, key=_solape)


def _metros_por_pixel(transform, crs, lat_centro: float) -> tuple[float, float]:
    """Tamaño REAL en metros de un píxel del raster (dx, dy).

    Si el CRS es proyectado (p.ej. estereográfico polar), el transform ya va
    en metros. Si es geográfico (grados), hay que multiplicar por el radio
    lunar y el coseno de la latitud (los meridianos se juntan hacia el polo).
    """
    import numpy as np

    if crs is not None and not crs.is_geographic:
        return abs(transform.a), abs(transform.e)

    # Raster geográfico: distancia real de 1 píxel en metros.
    # - vertical: arco por grado * grados de píxel (no depende de la latitud)
    # - horizontal: lo mismo multiplicado por cos(lat) (los meridianos se
    #   van juntando hacia el polo)
    dx_grados = abs(transform.a)
    dy_grados = abs(transform.e)
    arc_por_grado = 3.141592653589793 * RADIO_LUNA_M / 180.0
    dx_m = dx_grados * arc_por_grado * np.cos(np.radians(lat_centro))
    dy_m = dy_grados * arc_por_grado
    return float(dx_m), float(dy_m)


def _crateres_de_malla(z, z_transform, fila0: int, col0: int, crs,
                       dx_m: float, sigma: float = 1.5,
                       celda_m: float = 200.0,
                       radio_busqueda_m: float = 500.0) -> dict[str, Any]:
    """Detección APROXIMADA de cráteres sobre la malla regular del DTM.

    Misma heurística que `utilidades.detectar_crateres` pero sin nube de
    puntos: el DTM da una MALLA, así que el "nivel medio del terreno" se
    calcula con celdas de `celda_m` metros (media de píxeles) y un cráter
    es una celda hundida >sigma·σ respecto a la media de sus vecinas a
    menos de `radio_busqueda_m`.

    La profundidad está en la MISMA escala que la versión LOLA, así que los
    candidatos de ambas vías son comparables.

    `fila0`/`col0` son los índices ABSOLUTOS del raster donde empieza la
    ventana `z` (win.row_off / win.col_off): hacen falta para convertir
    índices de la matriz a coordenadas geográficas.
    """
    import numpy as np
    import warnings

    paso = max(1, int(round(celda_m / max(dx_m, 1e-6))))
    h = (z.shape[0] // paso) * paso
    w = (z.shape[1] // paso) * paso
    if h < paso or w < paso:
        return {"nota": "caja más pequeña que una celda de 200 m",
                "candidatos": []}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # Media de altura por celda: la matriz se recorta a múltiplos del
        # paso y se reordena en bloques paso×paso.
        bloques = z[:h, :w].reshape(h // paso, paso, w // paso, paso)
        media_celdas = np.nanmean(bloques, axis=(1, 3))
        # Celdas sin datos suficientes (sombras) quedan como NaN.
        n_validos = np.isfinite(bloques).sum(axis=(1, 3))
        media_celdas[n_validos < max(1, (paso * paso) // 2)] = np.nan

    M = media_celdas
    validos = np.isfinite(M)
    if validos.sum() < 9:
        return {"nota": "demasiadas celdas sin datos (sombras) para detectar",
                "candidatos": []}

    global_desv = float(np.nanstd(M))
    if global_desv <= 0:
        return {"metodo": "terreno uniforme (σ=0)", "candidatos": []}

    # Media de las vecinas a menos de radio_busqueda_m: acumulamos la suma
    # y el número de vecinos desplazando la matriz en todos los (dr, dc)
    # del cuadrado ±k. Con celdas de 200 m, k=2 cubre ±400 m ≈ los 500 m
    # pedidos, y son solo (2k+1)²-1 = 24 desplazamientos.
    k = max(1, int(round(radio_busqueda_m / (paso * dx_m))))
    suma = np.zeros_like(M)
    cuenta = np.zeros_like(M)
    filas_n, cols_n = M.shape
    for dr in range(-k, k + 1):
        for dc in range(-k, k + 1):
            if dr == 0 and dc == 0:
                continue
            # destino[i, j] acumula M[i+dr, j+dc]. Solo valen las celdas
            # donde ambos índices quedan dentro de la matriz.
            f_ori = slice(max(0, -dr), filas_n - max(0, dr))
            c_ori = slice(max(0, -dc), cols_n - max(0, dc))
            f_dst = slice(max(0, dr), filas_n - max(0, -dr))
            c_dst = slice(max(0, dc), cols_n - max(0, -dc))
            pedazo = M[f_ori, c_ori]
            suma[f_dst, c_dst] += np.nan_to_num(pedazo, nan=0.0)
            cuenta[f_dst, c_dst] += np.isfinite(pedazo)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        media_vecinos = np.where(cuenta > 0, suma / np.maximum(cuenta, 1),
                                 np.nan)
        hundimiento = media_vecinos - M
        # 'hundimiento > 0' = la celda está DEBAJO de sus vecinas (cráter).
        mask = (validos & (cuenta >= 4)
                & (hundimiento > sigma * global_desv))

    filas, columnas = np.where(mask)
    metodo = (f"depresiones de >{sigma}σ en celdas de {celda_m:.0f} m "
              f"vs vecinas a menos de {radio_busqueda_m:.0f} m "
              "(malla regular del DTM)")
    if filas.size == 0:
        return {"metodo": metodo, "n_candidatos": 0, "candidatos": []}

    # Orden por profundidad y nos quedamos con los 10 mayores.
    profundidades = hundimiento[filas, columnas]
    orden = np.argsort(profundidades)[::-1][:10]

    # Celdas -> coordenadas: los índices de `filas/columnas` son LOCALES a
    # la ventana leída; rasterio necesita filas ABSOLUTAS del raster.
    import rasterio.transform
    xs, ys = rasterio.transform.xy(
        z_transform,
        (filas + fila0).tolist(), (columnas + col0).tolist(),
        offset="center")

    # (x, y) están en la CRS del tile. Geográfica = (lon, lat) directamente;
    # proyectada (polos) = transformamos a la geográfica LUNAR IAU_2015:30100.
    xs_a = np.atleast_1d(np.asarray(xs, dtype="float64"))
    ys_a = np.atleast_1d(np.asarray(ys, dtype="float64"))
    if crs is not None and crs.is_geographic:
        lons, lats = xs_a, ys_a
    else:
        try:
            import rasterio.warp
            lons_w, lats_w = rasterio.warp.transform(
                crs, "IAU_2015:30100", xs_a.tolist(), ys_a.tolist())
            lons = np.atleast_1d(np.asarray(lons_w, dtype="float64"))
            lats = np.atleast_1d(np.asarray(lats_w, dtype="float64"))
        except Exception:
            lons = np.full(xs_a.shape, np.nan)  # sin CRS lunar: sin lat/lon
            lats = np.full(xs_a.shape, np.nan)

    candidatos = []
    for i in orden:
        lon_c = ((float(lons[i]) + 180.0) % 360.0) - 180.0
        candidatos.append({
            "lat": round(float(lats[i]), 5),
            "lon": round(lon_c, 5),
            "profundidad_est_m": round(float(profundidades[i]), 1),
        })
    return {
        "metodo": metodo,
        "n_candidatos": int(filas.size),
        "candidatos": candidatos,
    }


def analizar_sitio(lat: float, lon: float, radio: float,
                   items_stac: list[dict] | None = None,
                   aviso=None) -> dict[str, Any]:
    """Piloto completo del experimento A para UN sitio lunar.

    Pasos (cronometrados por separado):
      1. STAC: elegir el tile Kaguya TC DEM que cubre la caja (items
         precargados si el llamador ya hizo la búsqueda; si no, la hace).
      2. Descarga: bajar el GeoTIFF (~7 MB) a data/cache/dtm/ (si ya estaba,
         se salta la red).
      3. Cómputo: window read del trozo que interesa + pendiente + rugosidad
         + candidatos a cráter.

    Devuelve un dict con métricas EN EL MISMO FORMATO que la vía GDS
    ('elevacion'/'pendiente'/'rugosidad' con claves n/min/max/media/...) +
    metadatos + tiempos + cobertura. NUNCA lanza: ante cualquier fallo
    devuelve {'error': ..., 'fallback': 'lolardr'} para que `api.py` sepa
    que debe usar la vía GDS.
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

        # --- 1) STAC (reutiliza items si el llamador ya los trajo) ---------
        t0 = time.perf_counter()
        tile = _tile_dem_para(bbox_stac, lat, lon, items_stac)
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
            fila0, col0 = int(win.row_off), int(win.col_off)
            z = src.read(1, window=win).astype("float64")
            z_transform = src.transform  # ojo: es la del raster entero
            crs = src.crs
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
        # las métricas describen un trozo, no el sitio. `api.py` cae al
        # fallback LOLA en ese caso (comprueba 'confiable').
        out["confiable"] = out["pixeles_validos_fraccion"] >= 0.5

        dx_m, dy_m = _metros_por_pixel(z_transform, crs, lat)
        out["resolucion_m"] = round((dx_m + dy_m) / 2.0, 1)

        # Elevación (m sobre el radio de referencia lunar), formato estándar.
        out["elevacion"] = _a_estadisticas(
            validos,
            np.nanmin(z), np.nanmean(z), np.nanmedian(z),
            np.nanmax(z), np.nanstd(z))
        out["elevacion"]["n_pixeles"] = validos  # alias legible

        # Pendiente: gradiente por diferencia finita con distancia real.
        gy, gx = np.gradient(z, dy_m, dx_m)
        pend = np.degrees(np.arctan(np.hypot(gx, gy)))
        pend = pend[np.isfinite(pend) & np.isfinite(z)]
        out["pendiente"] = _a_estadisticas(
            pend.size, pend.min(), pend.mean(), np.median(pend),
            pend.max(), pend.std())
        out["pendiente"]["n_pixeles"] = int(pend.size)

        # Rugosidad: std de la altura dentro de celdas de ~100 m (misma
        # definición que la vía GDS -> comparable directamente).
        paso_r = max(1, int(round(100.0 / max(dx_m, 1e-6))))
        h = (z.shape[0] // paso_r) * paso_r
        w = (z.shape[1] // paso_r) * paso_r
        if h >= paso_r and w >= paso_r:
            bloques = z[:h, :w].reshape(h // paso_r, paso_r, w // paso_r, paso_r)
            # Un bloque entero en sombra (todo NaN) dispara un aviso de
            # numpy ('Degrees of freedom <= 0'): es esperable, se calla.
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rug_celda = np.nanstd(bloques, axis=(1, 3))
            rug = rug_celda[np.isfinite(rug_celda)]
            if rug.size:
                out["rugosidad"] = _a_estadisticas(
                    rug.size, rug.min(), rug.mean(), np.median(rug),
                    rug.max(), rug.std())
                out["rugosidad"]["n_celdas_100m"] = int(rug.size)
                out["rugosidad"]["tamano_celda_m"] = round(paso_r * dx_m, 1)
            else:
                out["rugosidad"] = {"nota": "sin celdas con datos suficientes"}
        else:
            out["rugosidad"] = {"nota": "caja más pequeña que una celda de 100 m"}

        # Cráteres/formaciones: heurística sobre la malla del DTM (grátis,
        # sin llamadas; los confirmados se verifican con el mapa geológico).
        out["crateres"] = _crateres_de_malla(z, z_transform, fila0, col0,
                                             crs, dx_m)

        out["computo_s"] = round(time.perf_counter() - t0, 1)
        out["total_s"] = round(
            out["stac_s"] + out["descarga_s"] + out["computo_s"], 1)
    except ImportError as exc:
        # rasterio/numpy no instalados: mensaje claro y fallback limpio.
        out["error"] = (f"dependencia ausente ({exc}): instala rasterio o "
                        "llama con usar_dtm=False")
        out["fallback"] = "lolardr"
    except Exception as exc:
        out["error"] = str(exc)
        out["fallback"] = "lolardr"
    return out
