"""api.py — LA función principal del colector.

    obtener_datos_sitio(cuerpo, lat, lon, radio) -> dict

Es la única función que la aplicación necesita llamar. Orquesta los módulos
temáticos y devuelve UN diccionario con TODOS los parámetros del reto:

    {
      "metadatos":  {...sitio, fechas, fuentes usadas...},
      "topografia": {elevacion, pendiente, rugosidad, crateres/formaciones},
      "termico":    {temperatura media/max/min, dia_noche, estacional},
      "superficie": {albedo/reflectancia, tipo_roca, minerales, polvo},
      "iluminacion":{fraccion diurna, energia solar, PSR, capas},
      "analogos_tierra": {...opcional...},
      "teselas_para_mapa": {...opcional, URLs WMTS para Leaflet...}
    }

Presupuesto de llamadas HTTP (Luna, caso normal):
    1  catálogo Treks        (todas las capas de una vez)
    2  GDS Diviner           (consulta + CSV: térmico + albedo en UNA ida)
    2  GDS LOLA              (consulta + CSV: elevación/pendiente/rugosidad)
    1  STAC USGS             (todos los DTM de golpe)
    1  PDS Search            (bundles Clementine para minerales)
    ------------------------
    7 llamadas en total      (+2 por capa si con_teselas=True, +~6 con tierra)

En Marte no hay LOLA/Diviner (son instrumentos lunares): la topografía sale
del STAC (DTM HiRISE/CTX) y el resto de capas del catálogo Mars Trek
(2 llamadas + opcional `ode_products` de nsac para metadatos).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import (
    analogos_tierra,
    constantes,
    iluminacion,
    superficie,
    termico,
    topografia,
    utilidades,
)


def guardar_en_registro(resultado: dict[str, Any],
                        ruta: str | None = None) -> Any:
    """Guarda la consulta en el registro `data/registro_sitios.json`.

    El registro es un JSON con una entrada POR SITIO (la clave incluye
    cuerpo, lat, lon y radio, p.ej. 'moon@-89.9,0.05±0.05'), así que si
    consultas dos veces el mismo sitio se ACTUALIZA su entrada (nueva fecha,
    mismos datos refrescados) en lugar de acumular duplicados.

    Cada entrada guarda:
      - 'fecha_consulta': cuándo se pidió.
      - 'resumen': los números principales con nombre y unidad, para mirar
        la base de sitios de un vistazo sin abrir el dict completo.
      - 'datos_completos': el diccionario entero (sin la lista cruda de
        puntos LOLA, que se queda resumida en n_puntos).

    Devuelve la ruta del registro. Nunca lanza error: si no se puede escribir
    (permisos, disco), devuelve el detalle del fallo y la consulta sigue.
    """
    import json
    import shutil
    from pathlib import Path

    ruta = Path(ruta or constantes.RUTA_REGISTRO)
    m = resultado.get("metadatos", {})
    clave = (f"{m.get('cuerpo')}@{m.get('lat')},{m.get('lon')}"
             f"±{m.get('radio_grados')}")

    # Copia ligera: mismo dict, sin los puntos crudos (ya están resumidos).
    copia = json.loads(json.dumps(resultado, default=str))  # deep-copy barato
    copia.get("topografia", {}).pop("puntos", None)

    # Cargar lo que ya había (o arrancar un registro nuevo con una nota).
    registro: dict[str, Any] = {}
    if ruta.exists():
        try:
            registro = json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            registro = {}  # JSON corrupto: se rehace (el anterior era cache)
    registro.setdefault(
        "_descripcion",
        "Registro de consultas de obtener_datos_sitio() — NSAC. Clave = "
        "cuerpo@lat,lon±radio; 'resumen' son los números con unidad y "
        "'datos_completos' el dict entero.")

    registro[clave] = {
        "fecha_consulta": m.get("consulta"),
        "resumen": _resumen_para_registro(resultado),
        "datos_completos": copia,
    }

    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Escritura segura: se escribe a un temporal y se reemplaza, para no
    # dejar el registro corrupto a medias si el programa se corta.
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(registro, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    shutil.move(str(temporal), str(ruta))
    return ruta


def _resumen_para_registro(resultado: dict[str, Any]) -> dict[str, Any]:
    """Extrae los números principales del dict, con nombre y unidad claros.

    Solo coge los valores que existan: un sitio sin GDS o con alguna fuente
    caída simplemente no aporta esas claves al resumen.
    """
    topo = resultado.get("topografia", {})
    term = resultado.get("termico", {})
    sup = resultado.get("superficie", {})
    ilu = resultado.get("iluminacion", {})

    def media(seccion: dict, clave: str) -> Any:
        valor = (seccion or {}).get(clave)
        return valor.get("media") if isinstance(valor, dict) else None

    dia_noche = term.get("dia_noche") or {}
    estacional = term.get("variacion_estacional") or {}
    energia = ilu.get("energia_solar") or {}

    resumen: dict[str, Any] = {
        "elevacion_media_m": media(topo, "elevacion_m"),
        "pendiente_media_grados": media(topo, "pendiente"),
        "rugosidad_media_m": media(topo, "rugosidad"),
        "temperatura_media_k": media(term, "temperatura_superficial"),
        "diferencia_dia_noche_k": dia_noche.get("diferencia_k"),
        "variacion_estacional_k": estacional.get("variacion_k"),
        "reflectancia_media": media(sup, "reflectancia_albedo"),
        "energia_solar_media_wm2": energia.get("energia_media_estimada_wm2"),
        "fraccion_diurna": ilu.get("fraccion_diurna_observada"),
        "n_puntos_lola": topo.get("elevacion_m", {}).get("n")
        if isinstance(topo.get("elevacion_m"), dict) else None,
        "n_observaciones_diviner": term.get("n_observaciones"),
    }
    # Se quitan las claves que no tenían dato, para que el resumen sea limpio.
    return {k: v for k, v in resumen.items() if v is not None}


def obtener_datos_sitio(cuerpo: str = "luna",
                        lat: float = -89.9,
                        lon: float = 0.05,
                        radio: float = 0.05,
                        usar_gds: bool = True,
                        con_teselas: bool = False,
                        incluir_tierra: bool = False) -> dict[str, Any]:
    """Devuelve el diccionario completo de parámetros para UN sitio.

    Parámetros:
      cuerpo         'luna' | 'marte' (| 'tierra' usa datos_tierra)
      lat, lon       centro del sitio en grados
      radio          semiancho de la caja de búsqueda, en grados
      usar_gds       False = salta las consultas GDS (lentas, minutos) y
                     deja solo capas/catálogos; útil para pruebas rápidas
      con_teselas    True = añade URLs WMTS listas para Leaflet/MapLibre
                     (2 llamadas HTTP extra por capa visual)
      incluir_tierra True = añade la sección de análogos terrestres (CMR/GIBS)

    Uso típico:
      from colector_datos import obtener_datos_sitio
      datos = obtener_datos_sitio("luna", -89.9, 0.05, 0.05)
    """
    cuerpo = utilidades.normalizar_cuerpo(cuerpo)

    resultado: dict[str, Any] = {
        "metadatos": {
            "cuerpo": cuerpo,
            "lat": lat,
            "lon": lon,
            "radio_grados": radio,
            "consulta": datetime.now().isoformat(timespec="seconds"),
            "fuentes": [],
        },
        "topografia": {},
        "termico": {},
        "superficie": {},
        "iluminacion": {},
    }

    cajas_g = utilidades.cajas_gds(lat, lon, radio)   # (minlat, maxlat, o, e)
    bbox_s = utilidades.caja_stac(lat, lon, radio)    # (o, s, e, n)
    projtype = "polar" if abs(lat) >= 80 else "eq"

    # ------------------------------------------------------------------
    # 1) Catálogo de capas Treks: UNA llamada, se reutiliza en todos los
    #    módulos (topografía, minerales, polvo, iluminación, PSR).
    # ------------------------------------------------------------------
    from nsac.sources import trek

    try:
        capas_trek = trek.layers(cuerpo, projtype=projtype)
        resultado["metadatos"]["fuentes"].append(
            f"Treks ({len(capas_trek)} capas, proyección {projtype})")
    except Exception as exc:
        capas_trek = []
        resultado["metadatos"]["fuentes"].append(f"Treks FALLÓ: {exc}")

    # ==================================================================
    # LUNA: datos crudos de LOLA + Diviner (las 2 únicas descargas reales)
    # ==================================================================
    if cuerpo == "moon":
        res_div: dict[str, Any] = {}
        res_lola: dict[str, Any] = {}

        if usar_gds:
            res_div = termico.datos_diviner(cajas_g)
            res_lola = topografia.elevacion_lola(cajas_g)

        # --- sección térmica ------------------------------------------
        term = {k: v for k, v in res_div.items() if not k.startswith("_")}
        if not term:
            term = {"nota": "usar_gds=False o GDS sin datos: descarga el CSV "
                            "de Diviner o usa las capas THEMIS de Treks"}
        resultado["termico"] = term

        # --- sección topográfica --------------------------------------
        topo: dict[str, Any] = {"fuente": "LOLA (GDS) + DTM Kaguya (USGS STAC) + Treks"}
        if res_lola.get("elevacion_m"):
            topo["elevacion_m"] = res_lola["elevacion_m"]
            geom = utilidades.pendiente_y_rugosidad(
                res_lola["puntos"], constantes.RADIO_DATUM_LUNA_M)
            topo["pendiente"] = geom.get("pendiente_grados")
            topo["rugosidad"] = geom.get("rugosidad_m")
            topo["metodo_pendiente_rugosidad"] = geom.get("metodo")
            topo["crateres_formaciones"] = utilidades.detectar_crateres(
                res_lola["puntos"], constantes.RADIO_DATUM_LUNA_M)
            topo["crateres_formaciones"]["referencias"] = [
                {"mapa_geologico_usgs": constantes.URL_MAPA_GEOLOGICO_LUNA},
            ]
        else:
            topo["elevacion_m"] = res_lola.get("error",
                                               "sin datos (usar_gds=False?)")
        try:
            topo["dtm_descargables"] = topografia.dtm_disponibles(
                cuerpo, bbox_s, lat)
            resultado["metadatos"]["fuentes"].append("USGS STAC (DTM)")
        except Exception as exc:
            topo["dtm_descargables"] = {"error": str(exc)}
        topo["capas_trek"] = topografia.capas_topografia_trek(capas_trek)
        resultado["topografia"] = topo

        # --- sección superficie ---------------------------------------
        resultado["superficie"] = superficie.datos_superficie(res_div, capas_trek)
        resultado["metadatos"]["fuentes"].append("PDS Search (Clementine)")

        # --- sección iluminación --------------------------------------
        resultado["iluminacion"] = iluminacion.datos_iluminacion(
            capas_trek, res_div)

    # ==================================================================
    # MARTE: sin LOLA/Diviner -> STAC (DTM) + capas Mars Trek
    # ==================================================================
    elif cuerpo == "mars":
        pc = constantes.PALABRAS_CLAVE_CAPAS

        topo: dict[str, Any] = {
            "fuente": "DTM HiRISE/CTX (USGS STAC) + capas Mars Trek",
            "nota_elevacion": ("La elevación puntual marciana requiere "
                               "descargar un DTM (ver dtm_descargables) o "
                               "leer las teselas DEM de Mars Trek."),
        }
        try:
            topo["dtm_descargables"] = topografia.dtm_disponibles(
                cuerpo, bbox_s, lat)
            resultado["metadatos"]["fuentes"].append("USGS STAC (DTM)")
        except Exception as exc:
            topo["dtm_descargables"] = {"error": str(exc)}
        topo["capas_trek"] = topografia.capas_topografia_trek(capas_trek)
        resultado["topografia"] = topo

        resultado["termico"] = {
            "fuente": "THEMIS (Mars Trek) / TES",
            "nota": ("No hay servicio tipo GDS para temperatura puntual en "
                     "Marte: la LST se obtiene de THEMIS (capas abajo) o "
                     "descargando products de MGS-TES/MRO-THEMIS en PDS ODE."),
            "capas_trek": utilidades.capas_por_keyword(capas_trek,
                                                       pc["temperatura"]),
        }
        resultado["superficie"] = superficie.datos_superficie(None, capas_trek)
        resultado["iluminacion"] = iluminacion.datos_iluminacion(
            capas_trek, None)

    # ==================================================================
    # TIERRA: se delega todo al módulo de análogos
    # ==================================================================
    else:  # earth
        return analogos_tierra.datos_tierra(lat, lon, radio)

    # ------------------------------------------------------------------
    # Opcionales: URLs de teselas para el visor y análogos terrestres
    # ------------------------------------------------------------------
    if con_teselas:
        pc = constantes.PALABRAS_CLAVE_CAPAS
        resultado["teselas_para_mapa"] = utilidades.urls_de_tesela(
            cuerpo, capas_trek,
            {"dem": pc["dem"],
             "pendiente": pc["pendiente"],
             "rugosidad": pc["rugosidad"],
             "iluminacion": pc["iluminacion"],
             "psr": pc["sombra"]})

    if incluir_tierra:
        resultado["analogos_tierra"] = analogos_tierra.datos_tierra(
            lat, lon, max(radio, 0.5))

    # ------------------------------------------------------------------
    # Registro: TODA consulta queda guardada en data/registro_sitios.json
    # (si el sitio ya estaba, se actualiza su entrada con la nueva fecha).
    # ------------------------------------------------------------------
    try:
        ruta_registro = guardar_en_registro(resultado)
        resultado["metadatos"]["registro"] = str(ruta_registro)
    except Exception as exc:
        # El registro es un extra: si no se puede escribir, la consulta
        # sigue siendo válida y solo anotamos el porqué.
        resultado["metadatos"]["registro"] = f"no se pudo guardar: {exc}"

    return resultado
