"""Ejemplo de uso del colector de datos NSAC.

Forma de ejecutar (desde la raíz del proyecto):

    python -m colector_datos.ejemplo_uso            # Luna, Shackleton, con GDS
    python -m colector_datos.ejemplo_uso --rapido   # sin GDS (solo catálogos)
    python -m colector_datos.ejemplo_uso --marte    # Marte, Jezero
    python -m colector_datos.ejemplo_uso --tierra   # análogo terrestre

--rapido existe porque las consultas GDS de PDS tardan MINUTOS (el GDS
genera y empaqueta los CSV a mano alzada); para probar que todo responde
basta con los catálogos.
"""

from __future__ import annotations

import argparse
import json

from . import constantes
from .api import obtener_datos_sitio


def main() -> None:
    parser = argparse.ArgumentParser(description="Colector de datos NSAC")
    parser.add_argument("--rapido", action="store_true",
                        help="salta las consultas GDS (tardan minutos)")
    parser.add_argument("--marte", action="store_true",
                        help="caracteriza Jezero (Marte) en vez de Shackleton")
    parser.add_argument("--tierra", action="store_true",
                        help="análogo terrestre (Atacama) en vez de la Luna")
    parser.add_argument("--sitio", default=None,
                        help="clave de constantes.SITIOS (shackleton, malapert, peary, jezero)")
    args = parser.parse_args()

    # Sitio elegido: el que pase --sitio, o el del modo, o el por defecto.
    clave = args.sitio or ("jezero" if args.marte else "shackleton")
    sitio = constantes.SITIOS[clave]
    print(f"Sitio: {clave} -> {sitio['nota']}")

    if args.tierra:
        from .analogos_tierra import datos_tierra
        datos = datos_tierra(-24.5, -69.25, 0.5)  # desierto de Atacama
    else:
        datos = obtener_datos_sitio(
            cuerpo=sitio["cuerpo"],
            lat=sitio["lat"],
            lon=sitio["lon"],
            radio=sitio["radio"],
            usar_gds=not args.rapido,
        )

    # `default=str` evita que un valor raro rompa el volcado a JSON.
    print(json.dumps(datos, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
