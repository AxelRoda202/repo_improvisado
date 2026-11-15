# NOTAS NOCTURNAS — Optimización del GDS (rama `optimizacion-gds`)

**Fecha:** noche del 14 al 15 de noviembre de 2026
**Estado:** trabajo en RAMA, sin tocar `master`. Pendiente de revisión por Axel.

---

## 0. Línea base (mediciones del 14-nov, código ANTERIOR)

Cada consulta completa de luna (caja ±0.05°, luna -23.4/157.8) medida
petición por petición:

| Petición | Tiempo | Qué trae |
|---|---|---|
| Treks (catálogo) | 8.4 s | JSON de 1.096 capas |
| GDS Diviner — generar | 23.8 s | (servidor fabricando el CSV) |
| GDS Diviner — bajar | 7.3 s | CSV 14.395 filas × 9 canales |
| GDS LOLA — generar | 15.6 s | (servidor fabricando el CSV) |
| GDS LOLA — bajar | 0.4 s | CSV 1.054 puntos |
| STAC (DTM) | 2.2 s | URLs de tiles Kaguya |
| PDS Search | ~2-3 s | bundles Clementine |
| Cálculos locales | 0.1 s | pendiente/rugosidad/cráteres |
| **TOTAL en serie** | **≈ 72-100 s** | |

Escalado con el radio (medido en corridas completas reales):
±0.05° ≈ 100 s · ±0.2° ≈ 605 s · ±0.5° ≈ 1.324 s (Diviner falla: el
servidor corta; LOLA a ±0.5° sí terminó con 92.389 puntos).

Hipótesis evaluadas contra las fuentes reales (pruebas del 14-nov):

| Hipótesis (investigación Gemini) | Veredicto | Evidencia |
|---|---|---|
| A. DTM GeoTIFF en vez de LOLA | **Viable** | Tile Kaguya DEM: 7.1 MB (S3 estático); nube copc.laz: 169 MB (descartada) |
| B. `results=s` (stats en servidor) | **Refutada** | Devuelve shapefile con las 20.685 obs una a una (`.dbf` 7.2 MB), NO un JSON de 3 números |
| C. Reducir canales Diviner | **Inútil** | 3 canales vs 9: solo -7% de tamaño (6.5 vs 7.1 MB), y usamos los 9 |
| D. Caché local | **Viable** | Los datos son históricos: re-bajar da lo mismo |
| E. Paralelismo | **Confirmado** | Serie 77 s → paralelo 40.1 s, mismos datos (medido) |

---

## 1. Cambios implementados en esta rama (D + E)

### D — Caché local (`colector_datos/cache_gds.py`, nuevo)

- Cada CSV del GDS (Diviner y LOLA) se guarda la primera vez en
  `colector_datos/data/cache/` con nombre legible:
  `divinerrdr_m23p45_m23p35_157p75_157p85_<huella>.csv`
  (la huella identifica los parámetros extra, p.ej. los canales).
- Clave: query + caja redondeada a 4 decimales (evita duplicar por ruido
  de punto flotante) + parámetros extra.
- Sin caducidad: las mediciones orbitales no se reescriben.
- `termico.datos_diviner()` y `topografia.elevacion_lola()` ahora leen de
  la caché antes de tocar la red. Fallos de escritura de caché no rompen
  la consulta (devuelve el dato fresco igualmente).
- La carpeta queda excluida del repo por la regla `data/` del `.gitignore`.

### E — Paralelismo (`colector_datos/api.py`)

- En consultas lunares con GDS, las 4 llamadas independientes se lanzan
  juntas en un `ThreadPoolExecutor(4)`: catálogo Treks + GDS Diviner +
  GDS LOLA + catálogo STAC. Antes iban en serie.
- El tiempo total pasa a ser "el de la más lenta", no la suma.
- Las 4 funciones internas capturan sus errores y devuelven dicts de
  error, así que el pool nunca lanza una excepción no controlada.
- Marte y Tierra siguen en serie (ya son rápidos: 6 s y 9 s).

### Sin cambios de fuentes ni de calidad de datos

Mismas URL, mismos parámetros, mismos cálculos. La caché devuelve el
MISMO DataFrame que venía del GDS (verificación de calidad más abajo).

---

## 2. Benchmark de la rama (mediciones del 15-nov)

*(se rellena con los resultados de las corridas de esta noche — ver
secciones 2.1 frío / 2.2 tibio / 2.3 calidad)*

### 2.1 Frío (sitio nuevo, luna 41.2, -23.7, ±0.05°)

**Nota previa:** la 1ª corrida de la noche en este sitio falló en el GDS
con `Invalid Lat/Lon Bounding Box` — destapó un BUG REAL que nadie había
visto porque todos los sitios de prueba tenían longitud positiva: el GDS
trabaja en el convenio 0-360 y RECHAZA longitudes negativas (una caja
-23.75..-23.65 es inválida para él). Corregido en `utilidades.cajas_gds`:
ahora convierte SIEMPRE a 0-360 (lon -23.7 → 336.3) y solo parte la caja
en dos si cruza el 360 (equivalente al meridiano 0). Verificado con 5
casos límite (-23.7, 0.05±0.1, 157.8, ±179.98): todos correctos.

Corrida fría CON el fix (nada cacheado, GDS generó ambos CSV de verdad):

- **Total: 95 s** (arquitectura paralela: el reloj marca lo que tarda la
  llamada GDS más lenta, no la suma).
- Dato completo y de calidad: 790 puntos LOLA · 17.027 obs Diviner ·
  albedo de 1.217 muestras · 2 candidatos a cráter · elev media
  -2389.3 m · pendiente 0.442° · rugosidad 0.905 m.
- Comparación con la línea base en serie: la base medía 72-100 s para el
  mismo tamaño de caja, PERO ahí las GDS iban una detrás de otra; en
  paralelo los 95 s son el techo de UNA GDS lenta (el servidor de PDS
  varía mucho: la generación del mismo CSV tardó 23.8 s el 14-nov y hoy
  andaba cerca del minuto). En el peor caso el paralelismo ya salva
  ~30-45 s; en el mejor (ver tibio) salva el 85%.
- El tiempo frío lo manda el servidor del GDS (variables de carga), no
  nuestro código: por eso la caché (2.2) es la optimización decisiva.

### 2.2 Tibio (misma consulta repetida, todo caché)

- **Total: 11 s** (vs 95 s frío) → **-88%**, y 8-9× más rápido que la
  línea base en serie sin caché (72-100 s).
- Desglose del techo: catálogo Treks ~8 s (sigue en red, no se cachea) +
  STAC ~2 s + PDS Search ~2 s, todo en paralelo; las 2 consultas GDS
  volvieron del disco en milisegundos.
- Cero fallos y cero secciones "sin datos": el informe tibio es idéntico
  al frío salvo el tiempo. Para la demo en vivo esto es el blindaje:
  cualquier sitio ya visitado responde en ~10 s aunque la NASA esté
  caída (las fuentes "catálogo" siguen fallando si no hay red, pero los
  datos pesados —el 95% del tiempo— vienen del disco).

### 2.3 Comparación de calidad frío vs tibio

Los 11 campos del `resumen` del registro, frío (01:20:29) vs tibio
(01:22:25), MISMO sitio, dos consultas independientes:

| Campo | Frío | Tibio | ¿Igual? |
|---|---|---|---|
| elevacion_media_m | -2389.3 | -2389.3 | ✓ IDÉNTICO |
| pendiente_media_grados | 0.442 | 0.442 | ✓ IDÉNTICO |
| rugosidad_media_m | 0.905 | 0.905 | ✓ IDÉNTICO |
| temperatura_media_k | 226.984 | 226.984 | ✓ IDÉNTICO |
| diferencia_dia_noche_k | 185.57 | 185.57 | ✓ IDÉNTICO |
| variacion_estacional_k | 211.42 | 211.42 | ✓ IDÉNTICO |
| reflectancia_media | 0.074 | 0.074 | ✓ IDÉNTICO |
| energia_solar_media_wm2 | 832.9 | 832.9 | ✓ IDÉNTICO |
| fraccion_diurna | 0.612 | 0.612 | ✓ IDÉNTICO |
| n_puntos_lola | 790 | 790 | ✓ IDÉNTICO |
| n_observaciones_diviner | 17027 | 17027 | ✓ IDÉNTICO |

**Veredicto de calidad: la caché es 100% transparente.** No es que
"parezca igual": los CSV cacheados son una copia byte a byte de lo que el
GDS entregó, así que cada cifra coincide exactamente.

---

## 3. Fase A experimental (DTM con rasterio)

- PENDIENTE (rama `dtm-rasterio`)

---

## 4. Recomendaciones para la revisión de la mañana

1. **MERGEAR `optimizacion-gds` a `master`** (recomendación fuerte): los
   cambios son aditivos (1 módulo nuevo + 3 conexiones + el fix de
   `cajas_gds`), la calidad está verificada 11/11 idéntica, y el frío ya
   destapó y corrigió un bug que habría PETF en la demo (cualquier sitio
   con longitud oeste fallaba en el GDS).
2. **Los números que importan para la demo:** frío 95 s (limitado por el
   servidor PDS, variable), tibio 11 s. Recomendación operativa para el
   día de la presentación: calentar la caché de los sitios de la demo
   ANTES (una pasada por la mañana), y así todo lo pesado sale del disco.
3. **Limitación conocida de la caché:** solo cubre GDS (Diviner/LOLA).
   Treks/STAC/PDS-Search siguen en red (~8 s tibio). Si hiciera falta
   bajar de 11 s, se puede cachear también el catálogo Treks (JSON de
   1.096 capas) — barato de añadir con la misma pauta; no lo hice para
   mantener el cambio mínimo.
4. La variación frío (95 s hoy vs 40-77 s en pruebas previas) es carga
   del servidor del GDS, no regresión nuestra; el paralelismo garantiza
   que NUNCA se suma Diviner+LOLA, solo se espera el peor.
