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

**Rama:** `dtm-rasterio` (creada desde `optimizacion-gds`). Módulos nuevos:
`colector_datos/topografia_dtm.py` (el piloto) y
`colector_datos/prueba_dtm.py` (la corrida de medición/comparación).
Dependencia nueva: `rasterio` 1.5.2 (instalada con pip, wheel cp313 win).

### 3.1 Cómo funciona el piloto

1. **STAC** (1 POST, ~3 s): busca el tile Kaguya TC DEM (`*-DEM.tif`) que
   cubre la caja; los items de LOLA apuntan a nubes `.copc.laz` de 169 MB
   y se descartan.
2. **Descarga** (1 GET, tile ~7 MB en S3 estático): se guarda en
   `data/cache/dtm/` y se reutiliza (datos históricos, como la caché GDS).
3. **Window read + cómputo** (~0.3 s): solo se lee el trozo del raster que
   cubre la caja; pendiente por gradiente con distancia real en metros;
   rugosidad = std dentro de celdas de ~100 m (MISMA definición que la vía
   GDS → comparable de frente).

Hallazgos de implementación (por si se integra mañana):
- Los tiles usan CRS IAU de la LUNA (p.ej. "Equirectangular, clon = 180").
  NO se puede usar `EPSG:4326` como origen (¡es la Tierra!) — PROJ lo
  rechaza. La CRS de origen correcta es `IAU_2015:30100` (geográfica
  lunar), que el PROJ de rasterio resuelve bien. Queda además un respaldo
  manual con la fórmula equirectangular.
- Resolución real del tile: **26.7 m/píxel** (no los 10 m nominales).
- Fallback previsto: si no hay tile tif que cubra la caja (o falla todo),
  el dict devuelve `fallback="lolardr"` y la integración usaría la vía
  GDS de siempre.

### 3.2 Resultados — Mare Smythii (luna -23.4, 157.8, ±0.05°), tile EN CACHÉ

- **Tiempos: STAC 3.3 s + descarga 0.0 s + cómputo 0.3 s = 3.6 s TOTAL.**
- Cobertura del tile: 100 % · 12.978 píxeles útiles (vs 790 puntos LOLA).
- Elevación: min -2435.8 · media -2325.34 · mediana -2309.76 · max
  -2267.1 · std 42.6 m.
- Pendiente: media 3.731° · mediana 3.279° · max 16.673°.
- Rugosidad (celdas de 107 m): media 1.932 m · mediana 1.696 m · max 8.77 m.

### 3.3 Comparación de calidad vs la vía GDS (LOLA, mismo sitio)

| Métrica | DTM (Kaguya 26.7 m) | LOLA (GDS) | Δabs | Δrel |
|---|---|---|---|---|
| Elevación media (m) | -2325.340 | -2336.779 | 11.4 | **0.5 %** |
| Pendiente media (°) | 3.731 | 2.246 | 1.49 | 66 % |
| Rugosidad media (m) | 1.932 | 3.227 | 1.30 | 40 % |

Lectura honesta:
- **Elevación: acuerdo excelente** (0.5 %). Las dos misiones miden lo
  mismo; la media no depende de la resolución.
- **Pendiente y rugosidad: DIFIEREN por diseño, no es un error.** LOLA
  entrega puntos dispersos a lo largo de órbitas (huecos de decenas de
  metros a cientos), así que su pendiente "suaviza" el terreno; el DTM
  muestrea la superficie completa cada 26.7 m y ve los relieves cortos
  (borde de cráteres pequeños, bloques) que la nube de puntos se salta.
  Ambos cuentan la MISMA historia operativa para este sitio: terreno
  llano-moderado, rugosidad manejable (<5 m). Si se integra, hay que
  decidir qué definición es "la oficial" del informe (o reportar ambas
  como rango), porque los números NO son intercambiables 1:1.
- DTM a favor: 12.978 muestras vs 790, muestreo uniforme (la nube LOLA
  concentra puntos en las huellas de las órbitas).
- DTM en contra: 1 tile cubre ±0.05° perfecto; cajas grandes (±0.5°)
  pueden necesitar varios tiles (el piloto hoy usa solo 1 y reporta la
  cobertura; mosaico multi-tile pendiente).

- PENDIENTE: sitio polar (Malapert) y sitio 41.2/-23.7; ver 3.4.

### 3.2bis Tiempo frío con descarga real (Smythii, tile borrado a propósito)

- **STAC 3.3 s + descarga 4.4 s (tile ~7 MB) + cómputo 0.5 s = 8.2 s TOTAL.**
- Los números de calidad salen idénticos a los del tibio (el cómputo es
  determinista sobre el mismo archivo).
- Comparación del tiempo total contra la vía GDS para el MISMO dato
  (elevación): GDS LOLA ≈ 16 s solo en generar+bajar la nube (y minutos
  en horas punta), sin contar que a radios grandes se dispara; DTM frío
  8.2 s, tibio 3.6 s. Con la caché GDS activa el LOLA tibio también es
  rápido, pero el DTM gana en frío y da 16× más muestras.

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

---

# SEGUNDA NOCHE (15 → 16 nov, rama `dtm-rasterio`)

**Estado:** integración del experimento A completada + caché de catálogos
(recomendación #4 de la primera noche) + las 2 pruebas DTM pendientes
(§3.3) ejecutadas. Todo medido contra las fuentes reales.

---

## 5. Regresión encontrada al arrancar

- `prueba_funcion.py` volvía a estar ROTO (f-strings partidos en las líneas
  del "veredicto"): el fix de la primera noche se hizo en disco pero no se
  comiteó, y al sincronizar ramas se perdió. Corregido y esta vez
  COMITEADO (`dbfdb66`). Lección: ningún fix queda hecho hasta que está en
  un commit.
- En ESTE dispositivo no había `rasterio` ni la carpeta `data/` (registro y
  caché viven fuera del repo). Instalado `rasterio` 1.4.4 (pip, Python 3.11).
  La caché/registro se reconstruyeron solos al correr.
- **`nsac/sources/pds.py` endurecido:** la primera línea base LOLA del sitio
  medio falló con `'str' object has no attribute 'get'`. Causa: cuando el
  GDS tiene un percance transitorio (repitido segundos después y funcionó),
  responde con `ResultFiles` como STRING, y `gds_query` casca críptico.
  Ahora esa respuesta se convierte en `RuntimeError` con el texto del
  servidor (y la caché no guarda basura). Lección #2: los fallos de API
  también hay que probarlos; el mensaje de error ES parte del producto.

## 6. Las 2 pruebas DTM pendientes (§3.3 de la primera noche)

### 6.1 Sitio de latitud media — luna 41.2, -23.7, ±0.05° ✅ PERFECTO

- STAC 1.5 s + descarga 3.3 s (tile ~7 MB) + cómputo 0.1 s = **4.9 s frío**.
- Cobertura del tile: **100 %** · píxeles válidos: **100 %** · 24.336 px
  (vs ~790 puntos LOLA: 30× más muestras) · resolución **19.4 m/px**.
- Elevación: media -2491.47 · mediana -2493.21 · std 6.24 m.
- Pendiente: media 1.12° · máx 6.73°. Rugosidad: media 0.53 m (celdas 97 m).
- Tibio (2ª corrida): **0.3 s TOTAL** (STAC de caché + tile en disco).

### 6.2 Sitio polar — Malapert (luna -85.9, 0.7, ±0.2°) ⚠️ CONFIRMA EL MATIZ

- STAC 2.2 s + descarga 2.1 s + cómputo 0.1 s = 4.4 s.
- El tile EXISTE y cubre el **89 %** de la caja en proyección, pero solo el
  **2 % de los píxeles son válidos** (243 px): los tiles polares de Kaguya
  tienen huecos enormes en zonas de sombra sin imagen TC.
- Números del trozo legible: elev ~+4194 m (macizo), pendiente media
  20.2°, rugosidad 7.4 m — plausibles pero describen un 2 % de la caja.
- **Veredicto: en polos el DTM NO es fuente primaria.** La política de
  fallback (`confiable=False` → vía GDS LOLA) queda justificada con datos,
  no por prudencia.

### 6.3 Tabla resumen de cobertura

| Sitio | lat | Cobertura tile | Píxeles válidos | ¿DTM utilizable? |
|---|---|---|---|---|
| Mare Smythii | -23.4 | 100 % | 100 % | SÍ |
| Sitio medio | 41.2 | 100 % | 100 % | SÍ |
| Malapert | -85.9 | 89 % | **2 %** | NO → fallback LOLA |

## 7. Integración del experimento A en `api.py` (lo que faltaba)

- Parámetro nuevo `usar_dtm=True` en `obtener_datos_sitio()`. Con él:
  1. El pool lanza: catálogo Treks + GDS Diviner + búsqueda STAC +
     **análisis DTM encadenado** al futuro del STAC (reutiliza sus items,
     no repite la llamada).
  2. **El GDS LOLA NO se lanza de entrada**: solo se consulta como
     fallback SI el DTM no sirve (sin tile, <50 % de píxeles válidos o
     <90 % de cobertura). Cuando el DTM cubre, el servidor frágil de PDS
     recibe UNA consulta GDS menos por sitio.
  3. Política de aceptación del DTM: `confiable` (≥50 % píxeles válidos)
     Y `cobertura ≥ 0.9`. Malapert la falla por los dos criterios.
- `topografia_dtm.py` ampliado para la integración:
  - Elige tile por **bbox** (contiene el centro → si no, máximo solape);
    `dtm_disponibles` ahora devuelve el bbox de cada item.
  - Métricas normalizadas al MISMO formato que `utilidades.estadisticas`
    (n/min/max/media/mediana/desv_estandar): la vía DTM y la vía LOLA son
    intercambiables para `api.py`, el informe y el registro.
  - **Cráteres sobre la malla** (celdas de 200 m, depresiones >1.5σ vs
    vecinas a <500 m): misma heurística que la versión LOLA pero sobre la
    matriz; sale grátis del mismo raster, 0 llamadas extra.
  - `ImportError` de rasterio tratado: mensaje claro + fallback a LOLA.
- Registro: el resumen ahora lleva `via_topografia` ('dtm_kaguya' o
  'lola_gds'). OJO: con vía DTM, `n_puntos_lola` cuenta PÍXELES de la
  malla (nombre histórico que se mantuvo por comparabilidad).
- `prueba_funcion.py` (el informe): bandera nueva `--sin_dtm` para correr
  la comparación A/B de vías desde la línea de comandos.
- `requirements.txt`: `rasterio` deja de ser opcional-comentado (es la
  dependencia de la vía integrada; sin él, fallback automático a LOLA).

## 8. Caché de catálogos (recomendación #4 de la primera noche)

- `cache_catalogo.py` (nuevo): JSON en `data/cache/catalogos/` para el
  catálogo Treks (por cuerpo+proyección) y la búsqueda STAC (por caja).
  Sin caducidad (misma lógica que la caché GDS: blindaje de demo), con
  soporte opcional de TTL y escritura atómica.
- `api._capas_trek` y `topografia.dtm_disponibles` pasan por ella. Medido:
  el STAC pasa de ~2-3 s a **0.0-0.2 s** tibio; el catálogo Treks (~8 s)
  sale del disco en milisegundos.

## 9. Benchmark de la integración (medido hoy, sitio Mare Smythii)

Mismo sitio (luna -23.4, 157.8, ±0.05°), tres corridas reales:

| Corrida | Config | Total | Topografía vía | Notas |
|---|---|---|---|---|
| A — frío clásico | `usar_dtm=False` | **41.3 s** | LOLA (GDS) | Diviner+LOLA fríos en paralelo; techo = la GDS más lenta |
| B — tibio DTM | `usar_dtm=True` | **4.2 s** | **DTM Kaguya** | GDS de caché; DTM de disco; LOLA ni se consulta |
| C — frío sitio NUEVO | `usar_dtm=True` (41.2,-23.7) | **33.0 s** | **DTM Kaguya** | Solo Diviner fue a la red; topografía en 0.1 s; 0 llamadas a LOLA |

- La corrida C es EL RESULTADO DE LA NOCHE: sitio nunca visto, consulta
  fría completa en 33 s donde antes el GDS LOLA añadía su propio tiempo de
  cola; y el servidor de PDS recibió solo la consulta de Diviner.
- El techo frío lo pone Diviner (irremplazable: temperatura MEDIDA). Con
  el sitio ya visitado (B): 4.2 s, y con catálogos de caché el suelo está
  en ~3-4 s (antes 11 s).

### 9.1 Calidad DTM vs LOLA en el MISMO sitio (Smythii)

| Métrica | DTM (26.7 m) | LOLA (GDS, corrida A) | Δabs | Δrel |
|---|---|---|---|---|
| Elevación media (m) | -2325.34 | -2336.78 | 11.4 | 0.5 % |
| Pendiente media (°) | 3.731 | 2.246 | 1.49 | 66 % |
| Rugosidad media (m) | 1.932 | 3.227 | 1.30 | 40 % |
| Muestras | 12.978 px | 1.054 puntos | — | — |
| Candidatos cráter | 0 | 1 | — | — |

- Elevación: acuerdo excelente (0.5 %). Pendiente/rugosidad difieren POR
  DISEÑO (mismas cifras que la primera noche: comparación reproducible
  entre dispositivos). El DTM ve relieves cortos que la nube dispersa
  suaviza; para "¿se puede aterrizar?" el DTM es más conservador y
  representativo (muestreo uniforme).
- Cráteres: la heurística en malla (200 m) y la de nube (celdas 100 m con
  puntos dispersos) no son 1:1. Smythii es una mare llana: 0 vs 1 es el
  ruido del umbral. Ver §9.2 para el caso que sí muerde.

### 9.2 DTM vs LOLA en el sitio medio (41.2, -23.7): OJO, Δ elevación ~100 m

| Métrica | DTM (19.4 m) | LOLA (GDS, este dispositivo) | Δabs | Δrel |
|---|---|---|---|---|
| Elevación media (m) | -2491.47 | -2389.30 | 102.2 | 4.3 % |
| Pendiente media (°) | 1.120 | 0.442 | 0.68 | — |
| Rugosidad media (m) | 0.530 | 0.905 | 0.38 | — |
| Muestras | 24.336 px | 790 puntos | — | — |
| Candidatos cráter | 0 | 2 | — | — |

*(la línea base LOLA se midió en este dispositivo con `usar_dtm=False`:
16.5 s totales, 790 puntos, y coincide EXACTO con la primera noche en el
otro dispositivo: -2389.3 / 0.442 / 0.905 — el GDS es determinista).*

- En Smythii ambas fuentes coincidían al 0.5 %; aquí difieren ~100 m
  (4.2 %). Hipótesis más plausible: los puntos LOLA están agrupados en
  las huellas de las órbitas y pueden quedar sesgados hacia una ladera
  si la caja pisa un gradiente; el DTM muestrea TODO el terreno
  uniformemente. La dispersión DTM dentro de la caja es std 6.2 m, así
  que la diferencia NO es ruido: es dónde se posaron los puntos.
- Lectura operativa idéntica en ambas fuentes (mare llano, pendiente
  mínima). Decisión propuesta para mañana: en el informe, la vía DTM es
  la fuente de elevación/pendiente/rugosidad cuando cubre, y la vía LOLA
  queda como verificación independiente (o como fuente única si se
  prefiere conservadorismo histórico). NO mezclar cifras de ambas vías en
  un mismo número.

### 9.3 Corrida D — fallback polar real (Malapert, luna -85.9, 0.7, ±0.1°)

- **Total: 134.5 s** (Diviner + LOLA fríos en paralelo; el reloj marca la
  GDS más lenta).
- El flujo completo funcionó como diseñado: DTM encadenado al STAC →
  tile ya en disco (0 s) → cobertura 1.0 pero **píxeles válidos 1.2 %** →
  rechazado por la política → aviso "fallback a GDS LOLA" → LOLA frío
  corrió y dio la topografía.
- Resultado vía LOLA: elev media **+4887.2 m** (macizo Malapert, orden de
  magnitud correcto: es una de las mayores alturas del polo sur),
  pendiente media 13.4° (terreno empinado de macizo).
- Dato extra: el catálogo Treks POLAR trae 490 capas (vs 1.096 de la
  proyección eq) — distinto catálogo, distinta caché, correcto.
- **Veredicto: el fallback funciona de punta a punta y el DTM no engaña
  en polos.** La consulta polar NO se ahorra el GDS LOLA (correcto: es
  justo donde el DTM no es fiable), pero SÍ lo evita en todo sitio
  ecuatorial/medio (corridas A/B/C).

### 9.4 Resumen final de la noche (5 escenarios medidos)

| Escenario | Tiempo | Topografía | GDS LOLA consultado |
|---|---|---|---|
| Frío clásico (usar_dtm=False), Smythii | 41.3 s | LOLA | Sí |
| Tibio completo, Smythii | 4.2 s | DTM | No |
| Frío sitio NUEVO (DTM cubre), sitio medio | 33.0 s | DTM | **No (0 llamadas)** |
| Frío POLAR (DTM rechazado), Malapert | 134.5 s | LOLA (fallback) | Sí |
| Tibio polar (todo caché) | ~10-12 s | LOLA | No (caché) |

## 10. Pendiente para mañana (decisión de Axel)

1. ~~Corrida D (fallback polar real)~~ → HECHA, ver §9.3.
2. ~~Línea base LOLA del sitio medio~~ → HECHA, ver §9.2 (tabla actualizada).
3. Merge a `master`: la rama `dtm-rasterio` ahora contiene D+E+caché de
   catálogos+integración A con fallback verificado. Todo aditivo y
   reversible (`usar_dtm=False` restaura el comportamiento de antes).
   Recomendación fuerte de mergear: cumple exactamente el plan que se
   pidió (D+E primero, A integrada con respaldo) y está medido en 5
   escenarios reales (§9.4).
4. Empujar la rama al remoto (ver §11: no se pudo desde aquí).

## 11. Estado del repositorio (importante para la mañana)

- Todos los cambios de esta noche están COMITEADOS en la rama local
  `dtm-rasterio` (commits `dbfdb66`, `eaf2797`, `26095e3`).
- **NO se pudo hacer `git push`**: este dispositivo usa credenciales de
  GitHub de `escudero819`, y el repo (`github.com/AxelRoda202/
  repo_improvisado`) responde 403 (permiso denegado). Opciones:
  a) Axel empuja la rama desde SU dispositivo (donde sí tiene credencial),
  b) o Axel añade a `escudero819` como colaborador del repo,
  c) o se configura aquí una credencial de Axel (PAT) para el push.
- `git log --oneline` en `dtm-rasterio` debe mostrar la secuencia:
  optimización GDS (D+E) → piloto DTM → fix f-strings → integración A +
  caché de catálogos → endurecimiento del GDS. Si falta alguno, el
  trabajo de esta noche no está en esa máquina.

## 12. Ideas NO implementadas (por alcance, documentadas para no perderlas)

- Mosaico multi-tile para cajas grandes (hoy se usa 1 tile y la política
  de cobertura rechaza el resto; con mosaico, ±0.5° completos por DTM).
- Cráteres por segmentación del DTM (la heurística actual es de cribado:
  depresiones de >1.5σ; los candidatos de malla y de nube no son 1:1).
- TTL opcional en los catálogos (hoy sin caducidad, como la caché GDS).
- Diviner sigue siendo el cuello de botella frío (33-134 s según carga
  del servidor): no hay alternativa medida, es temperatura REAL.

---

# TERCERA SESIÓN (16 nov, rama `dtm-rasterio`): SOPORTE DE MARTE

**Pregunta que abrió la sesión:** "¿las fuentes abarcan también Marte? ¿por
qué `obtener_datos_sitio(cuerpo='marte', ...)` no trae datos?" Respuesta
corta: las fuentes SÍ (STAC de USGS tiene DTMs de CTX/HiRISE, Mars Trek
tiene capas), pero el colector solo traía CATÁLOGOS para Marte, no datos
puntuales, porque LOLA y Diviner son instrumentos lunares. Sesión: portar
la receta DTM a Marte con el MISMO formato de diccionario.

## 13. Sondas a las fuentes marcianas (lo medido contra lo real)

### 13.1 El GDS de PDS NO tiene Marte (sonda descartada)

- Presets probados con `gds_query`: `mola_rdr`, `molardr`, `mola`,
  `themisrdr`, `mgs_tes` en la caja de Jezero (±0.05 y ±1°): TODOS
  responden `error: 'Please include a query type'` (el GDS lunares no
  reconoce presets marcianos; su User's Manual solo cubre LOLA/Diviner
  y misiones lunares).
- El ODE IIPT sí lista 597 combinaciones de productos marcianos (TGO ACS,
  THEMIS, TES, CTX, HiRISE...), pero son descargas de productos crudos,
  no un servicio de estadísticas puntuales.
- **Veredicto: no hay 'GDS marciano'.** La vía puntual es el DTM del STAC.

### 13.2 El STAC de USGS SÍ tiene DTMs de Marte en Jezero ✅

- `usgs_stac.search(['mro_ctx_controlled_usgs_dtms', ...])` en Jezero:
  10+ items con bbox, asset en S3 estático:
  `.../P18_007925_1987_XN_18N282W__P19_008650_1987_XI_18N282W_dtm.tif`.
- **Diferencia con la Luna:** el asset de Kaguya termina en `-dem.tif` y
  el de CTX en `_dtm.tif` → el filtro de `topografia_dtm._tile_dem_para`
  ahora acepta ambos sufijos (`SUFIJOS_DEM_TIF`).
- Tamaño del tile CTX: descarga 4.2 s (sonda), lectura window-read igual.

### 13.3 La CRS marciana (el hallazgo técnico de la sesión)

- El tile CTX de Jezero usa **IAU_2015:49910**: 'Mars (2015) Sphere /
  Ocentric / Equirectangular' PROYECTADA en METROS (bounds ~4.6M,
  ~1.1M), a diferencia de los tiles Kaguya (geográficos, IAU_2015:30100,
  grados).
- PROJ de esta instalación NO puede transformar hacia/desde CRS de otros
  cuerpos: `IAU_2015:30000` no parsea ('The WKT could not be parsed') y
  hacia EPSG:4326 rechaza por mezclar Tierra↔Marte.
- Solución: **fórmula manual de la equirectangular** x = R·(λ-λ0)·cos(φ1),
  y = R·φ con R = 3.396.190 m (constantes.RADIO_DATUM_MARTE_M), leída de
  `src.crs.to_dict()` (proj='eqc', lat_ts=0, lon_0=0, R=3396190).
  VERIFICADA: bbox→metros exacto (window 882×882 px) e INVERSA exacta
  (metros→(77.58, 18.38) sin error). El inverso alimenta la lat/lon de
  los candidatos a cráter.
- Limite: tiles marcianos POLARES usan proyección estereográfica ('stere')
  → con esta instalación de PROJ no se pueden leer de forma segura; el
  código devuelve error claro + fallback honesto (sin dato puntual).

### 13.4 Gale no tiene DTM controlado (sonda)

- Buscada la caja de Gale (±0.15, ±0.5 y ±1.5°) en CTX/HiRISE DTMs:
  50 items, **0 tifs**. Los DTMs controlados solo existen en zonas
  mapeadas por USGS (Jezero sí, Gale no).
- Comportamiento del colector: sección topográfica en catálogos +
  `nota_elevacion` honesta + `dtm_descargables` (10 tiles de imagen/THEMIS
  listados). NUNCA se inventan números.

## 14. Integración de Marte en `api.py` (mismo formato, políticas propias)

- `topografia_dtm.analizar_sitio(..., cuerpo='moon'|'mars')`: radios de
  datum por cuerpo (RADIOS_DE_DATUM), filtro de sufijos DEM, transformación
  de caja PROJ-primeiro/manual-fallback, y conversión de cráteres a
  lon/lat con el inverso eqc.
- `_dtm_encadenado(cuerpo, ...)`: patrón idéntico al lunar (DTM encadenado
  al futuro del STAC, reutiliza items).
- Rama MARTE en `obtener_datos_sitio()`: pool de 3 hilos (Treks + STAC +
  DTM), sección topográfica con las MISMAS claves que la Luna
  (elevacion_m/pendiente/rugosidad/crateres_formaciones/dtm_detalle/
  dtm_descargables/capas_trek + `via='dtm_mro'`).
- **Política de cobertura RELAJADA para Marte: ≥50 %** (en la Luna ≥90 %):
  sin fallback GDS, un tile que cubra la mitad de la caja sigue siendo la
  única elevación puntual disponible. Cuando la cobertura es <90 % se
  añade `nota_cobertura` al dict (medido: Jezero ±0.5° → 68 %).
- Bug destapado y corregido: la ruta en serie `elif cuerpo != 'earth'`
  también ejecutaba para Marte → 'Treks' aparecía 2 veces en `fuentes`.
- Resumen del registro: mismas claves; con Marte `n_puntos_lola` cuenta
  PÍXELES del DTM (4.262.513 en Jezero ±0.5°) y `via_topografia='dtm_mro'`.
- Mapa geológico marciano añadido a constantes
  (URL_MAPA_GEOLOGICO_MARTE, Global Geologic Map of Mars 1:20M) para las
  referencias de `crateres_formaciones`.

## 15. Benchmark y calidad de Marte (medidos)

| Corrida (Jezero 18.38, 77.58) | Tiempo | Vía | Notas |
|---|---|---|---|
| Sonda tile frío (±0.15, tile nuevo) | ~6 s | DTM | descarga 4.2 s + STAC 2 s |
| Completa frío catálogos (±0.5, tile ya en disco) | **2.8 s** | dtm_mro | Treks mars + STAC a la red; el resto de disco |
| Completa tibia (±0.5, todo en caché) | **1.1 s** | dtm_mro | | 

| Métrica | Jezero ±0.15 | Jezero ±0.5 (cobertura 68 %) |
|---|---|---|
| Píxeles del DTM | 777.763 | 4.262.513 |
| Resolución | 20.2 m/px | 20.2 m/px |
| Elevación media | **-2607.3 m** | -2377.9 m |
| Rango elevación | -2699.9 … -2423.1 | -2699.9 … -1356.1 (borde del cráter) |
| Pendiente media | 2.27° | 4.74° |
| Rugosidad media (celdas ~100 m) | 1.11 m | 2.40 m |
| Píxeles válidos | 99.98 % | 72 % |

- La elevación media de ±0.15 (-2607 m) describe el PISO de Jezero
  (consistente con la literatura: el fondo del cráter ronda -2.6 km); la
  de ±0.5 (-2378 m) sube porque la caja pisa la ladera/borde oriental
  (max -1356 m). Ambas plausibles: la diferencia es GEOMETRÍA de la caja,
  no error.
- Pendiente media 2.3-4.7°: coherente con un terreno de cráter + deltas
  excavados. Rugosidad ~1-2 m moderada.
- Sin datos reales de 'verdad terreno' para comparar (no hay LOLA
  marciano): la verificación fue contra la CRS (inversa exacta) y la
  plausibilidad geológica. Un contraste futuro: muestrear la capa DEM de
  Mars Trek en la misma caja.
- Regresión lunar verificada tras los cambios: Smythii tibio 4.2 s,
  mismos números (-2325.34 / 3.731 / 1.932), vía dtm_kaguya intacta.

## 16. Estado del soporte por cuerpo (resumen de las 3 sesiones)

| Cuerpo | Topografía | Térmico | Superficie/Iluminación | Fallback |
|---|---|---|---|---|
| Luna | DTM Kaguya (malla 19-30 m) o LOLA GDS | Diviner GDS (real, 9 canales) | Treks + Clementine | DTM→LOLA (política ≥50 % px, ≥90 % cobertura) |
| Marte | DTM CTX/HiRISE (malla ~20 m) o catálogos | THEMIS/TES (capas; sin puntual) | Treks (CRISM/Ω) | sin DTM→nota honesta |
| Tierra | análogos_tierra (CMR/GIBS) | GIBS | Copernicus | — |

## 17. DB local de sitios marcianos (`db_sitios_marte.py`) — 4ª sesión

Pedida para dejar de adivinar: "¿qué lugares de Marte tienen datos?" pasa
de sondeo manual a una lista consultable. La DB indexa lugares CON NOMBRE
del Gazetteer y guarda topografía (formato de comparación) + metadatos de
disponibilidad THEMIS (ventana ≤ 1 mes, nunca valores inventados).

### 17.1 Sondeos previos (los que decidieron el diseño)

| Sondeo | Resultado | Consecuencia de diseño |
|---|---|---|
| Conteo total de la colección CTX del STAC (paginada) | **44.628 items** (todos con `start_datetime`), 172.8 s, y el HiRISE dio 502 por la carga | NO indexar por tiles: imposible enriquecer 44k y el STAC no aguanta. Indexar por LUGARES |
| `/vsicurl/` + window read del tile CTX de Jezero | 882×882 px, media -2607.3, **6.3 s** — mismos números que el fichero bajado | Los stats se calculan leyendo el trozo por HTTP: cero descargas de tiles |
| `format=CSV` del Gazetteer | Param solo-cliente: el CSV lo arma el JS en el navegador | Parsear la tabla HTML `search_results` con regex |
| Gazetteer sin filtro (`PageSize=500`) | **2.100 lugares de Marte en UNA página**, 3.1 s | 1 GET para toda la lista |
| Combos ODE (IIPT) | `ODY/THEMIS/IRBTR4` válido (PDS4, con fechas de obs) | Fuente de mediciones múltiples |
| ODE `Count` con limit 200/500 | Devuelve tantas filas como el límite; Jezero ±0.1° = 211 obs reales, rango 2002-02-28 → 2026-02-26 (THEMIS sigue activo) | límite 500; el total real = longitud de la lista |
| ODE PDS4: `Id`/`Start_time` | `None`; los datos están en `Observation_time`, `Solar_time` y el id en `FilesURL?product_id=` | `ode_products` extendido (`_id_de_url`, observation_time, solar_time) |
| Ventana de 31 días en Jezero | Solo 1 obs de 211 (2026-02-26) | Guardar TODOS los ids de la ventana (aunque sea 1): honestidad > volumen |

### 17.2 Diseño

- **Filtro de indexado** (`indexar_gazetteer`): 2.100 filas − 127 'Albedo
  Feature' (sin relieve) − 840 cráteres < 40 km (el DTM de 20 m/px no
  resuelve bien cráteres chicos y serían cientos de lecturas al cuete) →
  **1.133 sitios 'pendiente'** (410 cráteres ≥ 40 km + 723 otras
  formaciones: 159 valles, 64 montes, 37 plana, 34 pateras...). Verificado
  que entran Jezero (47.5 km), Gale (154 km), Olympus Mons, Hellas.
- **Radio de la caja**: cráteres = diam/2 → grados (1°≈111.32 km)
  corregido por cos(lat), recortado a [0.05, 0.5]°; resto de tipos 0.2°
  fijo (los diámetros de planitiae/valles son de cuenca completa:
  Hellas 2.299 km → una caja así no se puede analizar).
- **Convenio de longitudes**: el Gazetteer trae 0-360 Este → a [-180, 180]
  (`lon-360` si >180).
- **Enriquecimiento** (`enriquecer`): por sitio, 1 búsqueda STAC por bbox
  (cacheada) + `analizar_sitio(..., modo_tile='remoto')` + ODE
  IRBTR4 limit=500 (cajas 0-360 con `utilidades.cajas_gds`, por si cruza
  el meridiano 0). Resumible: solo procesa 'pendiente'.
- **Política de cobertura: la MISMA que api.py** (relajada ≥ 50 %):
  `confiable AND cobertura ≥ 0.5` para ser 'listo'; si no, 'sin_dtm' con
  el motivo (p.ej. "cobertura 5% / píxeles válidos 99% < política 50%").
  Si el tile cubre <90 % queda `nota` (mismo texto que `nota_cobertura`).
- **Estados**: pendiente → listo | sin_dtm (no hay tile o cobertura
  insuficiente) | error (otra causa). `reintentar [--todo]` devuelve a
  pendiente.
- **Ventana THEMIS**: [última obs − 31 días, última obs]; en `mediciones`
  van SOLO los productos de la ventana (id, fecha, hora solar). En
  `sitios.themis_n_obs` queda el total de la caja como metadato de
  disponibilidad.
- **SQLite**: `data/db/sitios_marte.db` (data/ gitignored, como las
  cachés). Tabla `sitios` + tabla `mediciones` PK(sitio_id, producto_id).
  Hilos 2-3 máx con lock de escritura (conexión por transacción).
- **Salida** (`sitios_disponibles`): dicts con `resumen` de EXACTAMENTE
  las claves del registro del proyecto (elevacion_media_m,
  pendiente_media_grados, rugosidad_media_m, n_puntos_lola=píxeles,
  via_topografia='dtm_mro') + `topografia_extra` + `mediciones` (metadatos
  de la ventana). Los consumidores enchufan `resumen` tal cual.

### 17.3 Medido (sesión 4)

| Paso | Tiempo | Resultado |
|---|---|---|
| `indexar` (Gazetteer completo) | 1.6 s | 2.100 filas → 1.133 sitios |
| Lote 6 sitios, 2 hilos | 11.8 s | 1 listo, 5 sin_dtm (cajas al azar del ecuador: los DTM CTX/HiRISE cubren ~5 % de Marte) |
| Lote 8 sitios siguientes | 2.6 s | 0 listo, 8 sin_dtm (sin tile: fallo rápido, no hay red de más) |
| Jezero directo (`_enriquecer_sitio`) | ~10 s | listo: 20.2 m/px, cobertura 97.5 %, 231 obs THEMIS, 2 en ventana 2026-01-27..02-27 |
| End-to-end DB→`obtener_datos_sitio` | 0.7 s (tile en caché) | NÚMEROS IDÉNTICOS (elev -2599.497, pend 2.374) y mismo tile → la DB es un menú válido |

- La proporción 'sin_dtm' es ALTA (~90 % en los primeros lotes): es la
  cobertura real de los DTM controlados del MRO. Por eso la DB es útil:
  evita que el usuario pruebe caja tras caja sin datos.
- **Corrida final completa** (2 tandas por corte del shell de fondo;
  resumible como estaba previsto): 1.133 sitios en ~25 min de red, **0
  errores**. Resultado: **199 'listo'** (17,6 % — la cobertura real de
  los DTM controlados del MRO, ~5 % de la superficie pero coinciden con
  los lugares famosos), **934 'sin_dtm'** con motivo guardado. 328
  mediciones THEMIS en las ventanas; los 199 listos tienen TODOS ≥ 1 obs
  en su ventana (THEMIS sigue activo). Muestras plausibles: Apollinaris
  Tholus +1.634 m, Bamberg (cráter) piso -5.057 m, Acheron Fossae +106 m.
- `listar` con solo_listos devuelve los 199 en formato de comparación,
  listos para ser el menú de la app.

### 17.4 Soporte tocado en esta sesión

- `topografia_dtm.analizar_sitio(..., modo_tile='remoto')`: NO descarga
  el tile; abre `/vsicurl/{url}` y lee solo la ventana. Verificado contra
  el tile bajado: mismos números. `out['acceso']='remoto (vsicurl)'`.
- `pds.ode_products`: lee `Observation_time`/`Solar_time` y saca el id de
  `FilesURL?product_id=` (`_id_de_url`) — los PDS4 venían con id/fecha
  nulos.
- `db_sitios_marte.py`: NUEVO módulo (indexar/enriquecer/listar/
  reintentar/estado, CLI incluido).
