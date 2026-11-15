"""Constantes físicas, sitios de ejemplo y palabras clave.

Este archivo NO hace llamadas HTTP: solo guarda valores fijos que usan
todos los demás módulos. Tenerlos centralizados evita repetirlos y facilita
cambiar un sitio de estudio o un umbral en un único sitio.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# 0. Dónde vive el registro de consultas
# ---------------------------------------------------------------------------

# Cada llamada a obtener_datos_sitio() deja una entrada en este JSON. Vive en
# la subcarpeta 'data' DENTRO de colector_datos, para que todo lo que genera
# el colector quede junto. Si la carpeta no existe, se crea.
RUTA_REGISTRO = (Path(__file__).resolve().parent / "data"
                 / "registro_sitios.json")

# Tope del semiancho de la caja (en grados). El GDS de PDS genera los CSV
# sobre la marcha en su servidor y el tiempo crece DESPROPORCIONADAMENTE con
# el área: una caja de ±0.2° tarda ~10 min, una de ±1° puede tardar HORAS
# (y además reintenta 3 veces si el servidor devuelve 502/503). Por eso se
# recorta y se avisa: para más detalle, divide en sub-cajas más pequeñas.
RADIO_MAX_GRADOS = 0.5

# ---------------------------------------------------------------------------
# 1. Constantes físicas (valores estándar, sin llamadas a ninguna API)
# ---------------------------------------------------------------------------

# Irradiancia solar en el borde de la atmósfera terrestre, en W/m².
# La Luna está ~1 UA del Sol (igual que la Tierra), así que sirve para ambos.
IRRADIANCIA_SOLAR_WM2 = 1361.0

# Marte orbita a ~1.52 UA: su 'constante solar' es 1361/1.52² ≈ 586 W/m².
# Usar el valor terrestre inflaría la energía solar marciana 2.3 veces.
IRRADIANCIA_SOLAR_MARTE_WM2 = 586.0

# Radio del datum lunar (esferoide de referencia de LOLA/MOLA equivalente),
# en metros. La "elevación" de un punto LOLA es su radio menos este valor.
RADIO_DATUM_LUNA_M = 1737400.0

# Radio del datum marciano (areoide MOLA), en metros.
RADIO_DATUM_MARTE_M = 3396190.0

# ---------------------------------------------------------------------------
# 2. Sitios de ejemplo (presets listos para probar el colector)
# ---------------------------------------------------------------------------
# lat/lon en grados, radio = semiancho de la caja de búsqueda en grados.
# OJO: las cajas del GDS no deben cruzar el meridiano 0, por eso el
# "shackleton" usa lon=0.05 con radio 0.05 (la caja va de 0.0 a 0.1 E).
SITIOS = {
    "shackleton": {  # cráter Shackleton, polo sur lunar (dentro hay PSR)
        "cuerpo": "luna", "lat": -89.9, "lon": 0.05, "radio": 0.05,
        "nota": "Cráter Shackleton, candidato clásico de base en el polo sur.",
    },
    "malapert": {  # macizo Malapert, casi luz solar permanente
        "cuerpo": "luna", "lat": -85.9, "lon": 0.7, "radio": 0.2,
        "nota": "Macizo Malapert: cumbre con iluminación casi continua.",
    },
    "peary": {  # cráter Peary, polo norte lunar
        "cuerpo": "luna", "lat": 88.6, "lon": 33.3, "radio": 0.3,
        "nota": "Cráter Peary: colinas con ~90% de luz solar anual.",
    },
    "jezero": {  # cráter Jezero, Marte (sitio del rover Perseverance)
        "cuerpo": "marte", "lat": 18.38, "lon": 77.58, "radio": 0.5,
        "nota": "Cráter Jezero: delta fluvial, sinagogas de carbonatos.",
    },
    "Extranio": {  # cráter Gale, Marte (sitio del rover Curiosity)
        "cuerpo": "marte", "lat": -4.59, "lon": 137.44, "radio": 0.5,
        "nota": "Cráter Gale: sitio del rover Curiosity, monte Sharp.",
    },
}

# ---------------------------------------------------------------------------
# 3. Colecciones USGS STAC por cuerpo y por latitud
# ---------------------------------------------------------------------------
# Cada clave es una lista de ids de colección del STAC de Astrogeology
# (nsac.sources.usgs_stac). Se pasan TODAS en la misma llamada /search,
# así una sola petición devuelve los DTM de todas ellas.
COLECCIONES_STAC = {
    "luna_polo_sur": [
        "kaguya_terrain_camera_usgs_dtms_v2_southpolar",  # DTM 10 m del polo sur
        "lunar_orbiter_laser_altimeter",                 # puntos LOLA (COG/LAZ)
    ],
    "luna_polo_norte": [
        "kaguya_terrain_camera_usgs_dtms_v2_northpolar",
        "lunar_orbiter_laser_altimeter",
    ],
    "luna_global": [
        "kaguya_terrain_camera_usgs_dtms_v2",            # DTM global Kaguya TC
        "lunar_orbiter_laser_altimeter",
    ],
    "marte": [
        "mro_ctx_controlled_usgs_dtms",                  # DTM CTX (MRO)
        "mro_hirise_socet_dtms",                         # DTM HiRISE (más fino)
        "mo_themis_controlled_mosaics",                  # mosaicos THEMIS
    ],
}

# ---------------------------------------------------------------------------
# 4. Palabras clave para encontrar capas en el catálogo de Solar System Treks
# ---------------------------------------------------------------------------
# El catálogo de Treks se baja UNA vez (trek.layers) y luego se filtra en
# local con estas palabras clave, sin gastar más llamadas HTTP.
PALABRAS_CLAVE_CAPAS = {
    "dem": ["dem", "lola", "kaguya", "topograph", "elevat", "height", "mola"],
    "pendiente": ["slope"],
    "rugosidad": ["rough", "rugos"],
    "crateres": ["crater"],
    "geologia": ["geolog", "formation", "unit", "map"],
    "temperatura": ["temp", "themis", "bolometric", "heat flow"],
    "albedo": ["albedo", "reflect", "brightness", "clementine"],
    # 'crism/omega/tes' son los espectrómetros marcianos; 'olivine',
    # 'carbonate', 'chloride', 'sulfate' y 'hematite' son los minerales
    # clave de la geología marciana (y Kaguya mapea olivina también en Luna).
    "minerales": ["mineral", "iron", "titanium", "feo", "tio2", "element",
                  "thorium", "composition", "spectra", "crism", "omega",
                  "olivine", "carbonate", "chloride", "sulfate", "hematite"],
    "polvo": ["dust", "h-parameter", "h param", "regolith", "soil"],
    "iluminacion": ["illum", "light", "insolat", "sun"],
    "sombra": ["psr", "shadow", "permanently"],
}

# ---------------------------------------------------------------------------
# 5. Búsquedas PDS y enlaces estáticos útiles
# ---------------------------------------------------------------------------

# Palabra clave para buscar bundles PDS4 con información mineralógica.
# Clementine UVVIS mapeó albedo y abundancias relativas de Fe y Ti de toda
# la Luna; es la fuente PDS más directa para "minerales predominantes".
BUSQUEDA_PDS_MINERALES = "clementine"

# Mapa geológico unificado de la Luna (USGS) para "formaciones geológicas".
URL_MAPA_GEOLOGICO_LUNA = (
    "https://astrogeology.usgs.gov/search/map/"
    "Moon/Geology/Unified_Geologic_Map_of_the_Moon_7_5M_v2"
)

# Variables terrestres que se piden a CMR cuando se incluye un análogo.
# Cada tupla es (nombre del parámetro, palabra clave para search_collections).
VARIABLES_CMR = [
    ("elevacion", "aster global dem"),
    ("temperatura_superficial", "land surface temperature"),
    ("albedo_reflectancia", "albedo"),
    ("humedad_suelo", "soil moisture"),
]
