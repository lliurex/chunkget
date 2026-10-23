# Tareas 001 — Implementación del MVP de chunkget

Derivadas de `spec.md` y `plan.md`. Las referencias «D5», «7.5», «4.4»… remiten a secciones de `plan.md`.

## Reglas de trabajo
- **Tamaño:** cada tarea cabe en 20–30 minutos. Si una se alarga, se divide antes de seguir.
- **Orden:** las tareas están ordenadas por dependencia. No se empieza una tarea sin tener hechas las que figuran en «Depende de».
- **Tests (constitución §4):** cada tarea incluye sus propios tests, que se escriben con el código. Los tests solo usan red local (`127.0.0.1`).
- **Cierre de cada tarea:** `pytest -q` pasa completo. Es parte de «Hecho cuando» aunque no se repita.
- **Divergencias (constitución §3):** si al implementar el código diverge de la spec o del plan, se para y se corrige primero la spec, luego el plan y después el código.
- **Código en inglés** y mensajes con `gettext` (constitución §6).
- **Git:** la gestión de commits y ramas la decide el usuario; las tareas no incluyen comandos de git.

## Nota sobre RF6
La spec (RF6) y el plan (D5 y 7.4) coinciden: un manifest indicado por URL se descarga **a un fichero local** para usos posteriores. Las tareas T44 y T45 implementan el guardado; T72 y T73 lo exponen en la CLI.

---

## Fase 0 — Esqueleto y utilidades base

- [x] **T01 — Esqueleto del paquete y test de humo**
  - RF/RNF: RNF1
  - Depende de: —
  - Crea `conftest.py` (vacío), `pyproject.toml` (solo `[build-system]`), `setup.cfg` (metadatos y `console_scripts` `chunkget = chunkget.cli:main`), `chunkget/__init__.py` (versión), `chunkget/__main__.py` y `tests/test_smoke.py`.
  - Hecho cuando: `pytest -q` termina con código 0 y ejecuta `test_smoke.py`, que importa `chunkget` y comprueba que existe `chunkget.__version__`.

- [x] **T02 — `ExitCode`**
  - RF/RNF: RNF3
  - Depende de: T01
  - `errors.py` con la enumeración de la tabla 7.5 (0, 1, 2…13, 130, 143).
  - Hecho cuando: `tests/test_errors.py` comprueba que los nombres y valores coinciden con la tabla 7.5, que no hay valores repetidos y que `ExitCode.OK == 0`.

- [x] **T03 — `i18n.py`**
  - RF/RNF: RNF2
  - Depende de: T01
  - Funciones `_` y `ngettext` con dominio `chunkget`, `fallback=True`, y una función para inyectar un objeto de traducción (para tests).
  - Hecho cuando: `tests/test_i18n.py` comprueba que, sin catálogo, `_("x")` devuelve `"x"`, y que con una traducción inyectada que transforma el texto, `_` y `ngettext` devuelven el texto transformado.

- [x] **T04 — Jerarquía de excepciones**
  - RF/RNF: RNF2, RNF3
  - Depende de: T02, T03
  - `ChunkgetError` (con `exit_code`; recibe el mensaje ya traducido: cada literal se marca con `_()` en el punto de la llamada, `ChunkgetError(_("..."))`, y se interpola después con `.format(...)`, para que `xgettext` lo extraiga sin opciones especiales) y una subclase por cada código de 7.5: `UsageError`, `SourceError`, `UserDeclinedError`, `ManifestInvalidError`, `NetworkError`, `RetriesExhaustedError`, `GlobalHashMismatchError`, `NoSpaceError`, `FilesystemError`, `ServerIncompatibleError`, `AlreadyRunningError`, `StateInvalidError`, `InterruptedByUser`. Más `OutputExistsError` y `DestinationExistsError`.
  - Hecho cuando: `tests/test_errors.py` comprueba que cada subclase expone el `ExitCode` de 7.5, que es subclase de `ChunkgetError`, y que el mensaje recibido se conserva tal cual y, cuando el literal está marcado con `_()`, pasa por la traducción inyectada. `tests/test_architecture.py` comprueba con `ast` que toda excepción del paquete se construye con `_("literal")` como mensaje.

- [x] **T05 — Eventos de progreso**
  - RF/RNF: RNF4
  - Depende de: T01
  - `events.py` con dataclasses para: inicio de pasada, fragmento terminado (índice, total, bytes), reintento, inicio de verificación global, fin.
  - Hecho cuando: `tests/test_events.py` crea cada evento y comprueba que son inmutables (`frozen`) y tienen los campos acordados.

- [x] **T06 — Test de arquitectura (núcleo sin CLI)**
  - RF/RNF: RNF4
  - Depende de: T01
  - `tests/test_architecture.py` analiza con `ast` los ficheros de `chunkget/` y falla si alguno, salvo `cli.py` y `__main__.py`, importa `argparse`, usa `input`, `print`, `sys.exit` o importa `chunkget.cli`.
  - Hecho cuando: el test pasa con el código actual y, con un fichero temporal de prueba que contiene `import argparse`, el mismo análisis lo detecta (comprobado en un test unitario del propio detector).

---

## Fase 1 — Configuración

- [x] **T07 — Valores por defecto**
  - RF/RNF: RF1.2, RF1.4
  - Depende de: T01
  - `config.py` con las constantes de la sección 2 del plan (100 MiB, `sha256`, 5 reintentos, 30 s, 1 MiB de búfer, 64 MiB de manifest, 250 000 fragmentos, 3 fallos de red consecutivos).
  - Hecho cuando: `tests/test_config.py` comprueba cada constante contra la tabla de la sección 2.

- [x] **T08 — `parse_size`**
  - RF/RNF: RF1.3
  - Depende de: T04, T07
  - Convierte `"4096"`, `"4K"`, `"100M"`, `"1G"` (potencias de 1024) en bytes; rechaza vacío, negativos, sufijos desconocidos y decimales.
  - Hecho cuando: tests parametrizados comprueban los valores válidos y que cada entrada inválida lanza `UsageError` cuyo mensaje incluye el formato admitido.

- [x] **T09 — Validadores de opciones numéricas**
  - RF/RNF: RF1.3
  - Depende de: T08
  - Validan `chunk_size` (1 B – 1 GiB), `max_retries` (0–100) y `timeout` (1–3600).
  - Hecho cuando: tests comprueban los límites inclusivos y que un valor fuera de rango lanza `UsageError` con el rango válido en el mensaje.

- [x] **T10 — Rutas por defecto**
  - RF/RNF: RF1.4
  - Depende de: T07
  - Funciones para el directorio de estado (`$XDG_STATE_HOME/chunkget` o `~/.local/state/chunkget`), el manifest de salida por defecto (`./<name>.chunkget.manifest`) y el destino por defecto (`./<name>`).
  - Hecho cuando: tests con variables de entorno simuladas comprueban las tres rutas, incluido el caso sin `XDG_STATE_HOME`.

---

## Fase 2 — Hashing

- [x] **T11 — Registro de algoritmos y formato `alg:hex`**
  - RF/RNF: RF1.1, RF1.3
  - Depende de: T04
  - `hashing.py`: lista soportada (`sha256`, `sha384`, `sha512`, `sha3_256`, `sha3_512`), `format_hash`, `parse_hash` y validación de longitud del hex por algoritmo.
  - Hecho cuando: tests comprueban que `md5` y `sha1` se rechazan con `UsageError` que lista los algoritmos soportados, y que `parse_hash` rechaza mayúsculas, longitud incorrecta y prefijo desconocido.

- [x] **T12 — Hash incremental y de fichero**
  - RF/RNF: RF1.1, RF11, RNF2
  - Depende de: T11
  - Objeto hasher incremental y `hash_file(path)` con búfer de 1 MiB.
  - Hecho cuando: tests comprueban que el resultado coincide con `hashlib` para un fichero de varios búferes y para el fichero vacío, y que el hash de un fichero de 5 MiB no lee más de 1 MiB por llamada (comprobado con un fichero simulado que registra el tamaño de lectura).

---

## Fase 3 — Modelo del manifest

- [x] **T13 — Modelo y serialización**
  - RF/RNF: RF1.1, RF1.1.1
  - Depende de: T11
  - `manifest.py`: dataclasses `Manifest`/`Chunk` y `to_json` con claves en el orden de 4.1, indentación y UTF-8.
  - Hecho cuando: `tests/test_manifest.py` comprueba que la salida es JSON válido con exactamente las claves de 4.1 y 4.2, en ese orden, y que contiene saltos de línea e indentación (legible).

- [x] **T14 — Carga desde bytes: estructura y tipos**
  - RF/RNF: RF1.1, caso «manifest corrupto»
  - Depende de: T13, T04
  - `load_manifest(data)` valida JSON, que sea un objeto con exactamente las claves de 4.1 y 4.2 y los tipos correctos (invariante 1).
  - Hecho cuando: tests parametrizados comprueban que JSON inválido, clave faltante, clave sobrante y tipo incorrecto lanzan `ManifestInvalidError` (código 5), y que un manifest válido se carga.

- [x] **T15 — Validación de versión, nombre y URL**
  - RF/RNF: RF1.1, caso «manifest corrupto»
  - Depende de: T14
  - Invariantes 2, 3 y 4.
  - Hecho cuando: tests comprueban que se rechazan: versión mayor y menor (con mensajes distintos), nombre vacío, `.`, `..`, con `/`, `\`, NUL, de más de 255 bytes, y URL sin host o con esquema distinto de `http`/`https`.

- [x] **T16 — Validación de `chunk_size` y hashes**
  - RF/RNF: RF1.1, caso «manifest corrupto»
  - Depende de: T14, T11
  - Invariantes 5 y 6.
  - Hecho cuando: tests comprueban que se rechazan `chunk_size` 0 y mayor que 1 GiB, hashes con algoritmos mezclados o no soportados, hex de longitud incorrecta y hex con mayúsculas.

- [x] **T17 — Validación de la lista de fragmentos**
  - RF/RNF: RF1.1, caso «manifest corrupto», caso «fichero vacío o menor que un fragmento»
  - Depende de: T14
  - Invariantes 7 y 8, y el límite de 250 000 fragmentos.
  - Hecho cuando: tests comprueban que se rechazan: `id` no consecutivo, hueco o solape, último `end` distinto de `size`, fragmento mayor que `chunk_size`, nº de fragmentos distinto de `ceil(size/chunk_size)` y más de 250 000. Se aceptan `size = 0` con `chunks = []` y un único fragmento menor que `chunk_size`.

- [x] **T18 — Carga desde fichero**
  - RF/RNF: RF1.1, RF4, RF6
  - Depende de: T15, T16, T17
  - `load_manifest_file(path)` con límite de 64 MiB (invariante 9).
  - Hecho cuando: tests comprueban que un fichero inexistente lanza `SourceError` (código 3), uno de más de 64 MiB `ManifestInvalidError` (código 5), y que `to_json` seguido de `load_manifest_file` devuelve un manifest igual (ida y vuelta).

---

## Fase 4 — Generación del manifest desde un fichero

- [x] **T19 — Cálculo de fragmentos y hash global en una pasada**
  - RF/RNF: RF2, RF1.1
  - Depende de: T12
  - `manifest_builder.py`: lee el fichero una vez y devuelve la lista de fragmentos y el hash global.
  - Hecho cuando: un test con un fichero de N bytes y fragmento F comprueba que hay `ceil(N/F)` hashes que coinciden con los calculados con `hashlib` por separado, y que el hash global coincide con el de `hashlib` sobre todo el fichero.

- [x] **T20 — Casos límite del cálculo**
  - RF/RNF: RF2, caso «fichero vacío o menor que un fragmento»
  - Depende de: T19
  - Hecho cuando: tests comprueban: fichero vacío (0 fragmentos y hash global de la cadena vacía), fichero menor que el fragmento (1 fragmento), fichero múltiplo exacto del fragmento y último fragmento más corto.

- [x] **T21 — Construir el `Manifest` completo**
  - RF/RNF: RF2, RF1.2, RF1.3
  - Depende de: T20, T18, T05
  - Función que recibe ruta, URL, tamaño de fragmento y algoritmo, usa los valores por defecto si no se indican, informa del progreso al *listener* y devuelve un `Manifest` validado. `name` es el nombre base del fichero.
  - Hecho cuando: tests comprueban que sin parámetros usa 100 MiB y `sha256`, que un algoritmo no soportado lanza `UsageError`, que el `Manifest` pasa la validación y que el *listener* recibe un evento por fragmento.

---

## Fase 5 — Servidor de pruebas y cliente HTTP

- [x] **T22 — Servidor de pruebas con `Range`**
  - RF/RNF: constitución §4
  - Depende de: T01
  - `tests/helpers/http_server.py`: servidor `http.server` en `127.0.0.1`, puerto efímero, que sirve bytes y responde `206` con `Content-Range` a peticiones con `Range`, y fixture de pytest.
  - Hecho cuando: un test usa `urllib` contra el servidor y comprueba que un `Range: bytes=2-5` devuelve estado 206, 4 bytes y un `Content-Range` correcto, y que el servidor se cierra al terminar el test.

- [x] **T23 — Fallos de datos inyectables**
  - RF/RNF: constitución §4, caso «corte de red»
  - Depende de: T22
  - El servidor puede, por configuración: cortar la conexión tras N bytes, corromper un fragmento concreto y registrar las peticiones recibidas.
  - Hecho cuando: tests comprueban cada fallo contra `urllib` (lectura truncada con excepción, bytes distintos en el fragmento elegido) y que el registro de peticiones refleja las cabeceras `Range`.

- [x] **T24 — Fallos de estado y cabeceras inyectables**
  - RF/RNF: constitución §4
  - Depende de: T22
  - El servidor puede: ignorar `Range` (devolver 200), devolver otro total en `Content-Range`, añadir `Content-Encoding: gzip`, responder una secuencia de códigos (404, 429, 503…) y redirigir a otro esquema.
  - Hecho cuando: tests comprueban cada comportamiento con `urllib` o `http.client`.

- [x] **T25 — Validación de URL y redirecciones**
  - RF/RNF: D5, RF4
  - Depende de: T04
  - `http.py`: función que rechaza esquemas distintos de `http`/`https` y *handler* de redirecciones que rechaza redirigir a otros esquemas.
  - Hecho cuando: tests comprueban que `file://`, `ftp://` y una URL sin host lanzan `SourceError`, y que una redirección `http` a `file://` (servidor de pruebas) falla.

- [x] **T26 — Clasificación de errores HTTP**
  - RF/RNF: D5, RF10
  - Depende de: T04
  - Función pura que clasifica una excepción o un estado en: reintentable, fatal (código 6), incompatible (código 11) o de origen (código 3).
  - Hecho cuando: tests parametrizados cubren toda la tabla de D5: reset, timeout, 5xx, 408, 429 → reintentable; 403, 404, fallo de certificado → fatal; 200 en lugar de 206, total distinto y `Content-Encoding` → incompatible.

- [x] **T27 — Lectura en memoria de un recurso**
  - RF/RNF: RF6, RF4
  - Depende de: T25, T26, T22
  - `fetch_bytes(url, max_bytes, timeout)` con tope de 64 MiB.
  - Hecho cuando: tests contra el servidor comprueban que devuelve el contenido, que un recurso mayor que el tope lanza `ManifestInvalidError`, que un 404 lanza `SourceError` (código 3) y que un timeout lanza `SourceError`.

- [x] **T28 — Petición de un rango: caso correcto**
  - RF/RNF: RF7, RF9
  - Depende de: T25, T26, T22
  - `open_range(url, start, end, timeout)` envía `Range: bytes=start-(end-1)`, `Accept-Encoding: identity` y `User-Agent: chunkget/<versión>`, y entrega un flujo.
  - Hecho cuando: un test comprueba el contenido recibido del fragmento y que el registro del servidor muestra exactamente esas tres cabeceras.

- [x] **T29 — Petición de un rango: errores**
  - RF/RNF: RF7, RF9, D5
  - Depende de: T28, T24, T23
  - Valida estado 206, `Content-Range` exacto con el total esperado, `Content-Encoding` y longitud recibida.
  - Hecho cuando: tests comprueban que: respuesta 200 → `ServerIncompatibleError` (11); total distinto → 11; `Content-Encoding: gzip` → 11; 404 → `NetworkError` (6); 503 y corte a mitad → error reintentable.

- [x] **T30 — Descarga simple a fichero**
  - RF/RNF: RF3, D4
  - Depende de: T27
  - `simple_download(url, path, timeout)`: GET en streaming directamente a la ruta indicada, sin fichero temporal.
  - Hecho cuando: un test descarga un recurso de varios búferes y el fichero coincide byte a byte; durante la descarga el directorio solo contiene el fichero destino.

- [x] **T31 — Descarga simple con reanudación**
  - RF/RNF: RF3, D4
  - Depende de: T30, T23
  - Si la conexión se corta, reanuda con `Range` desde el tamaño ya escrito, con reintentos y espera inyectable (D7).
  - Hecho cuando: un test con corte tras N bytes comprueba que el fichero final es idéntico, que la segunda petición pidió `Range: bytes=N-` y que, con cortes en todos los intentos, se lanza `NetworkError` tras `max_retries` intentos sin esperar tiempo real.

---

## Fase 6 — Almacenamiento

- [x] **T32 — Comprobación de espacio**
  - RF/RNF: caso «no hay espacio»
  - Depende de: T04
  - `storage.check_free_space(directory, needed)` con `shutil.disk_usage`.
  - Hecho cuando: tests con `disk_usage` sustituido comprueban que con espacio justo pasa, con un byte menos lanza `NoSpaceError` (código 9), y que el cálculo para un destino existente usa `size − tamaño actual`.

- [x] **T33 — Creación del destino con el tamaño del manifest**
  - RF/RNF: RF7
  - Depende de: T32
  - `storage.prepare_destination(path, size)`: crea o extiende el fichero al tamaño exacto, con `os.posix_fallocate` y, si no está soportado, con truncado.
  - Hecho cuando: tests comprueban que el fichero resultante mide `size` (incluido `size = 0`) y que, con `posix_fallocate` simulado como no soportado, se usa el truncado y el tamaño sigue siendo el correcto.

- [x] **T34 — Escritura de un fragmento en su posición**
  - RF/RNF: RF7, RF9
  - Depende de: T33, T12
  - `storage.write_chunk(path, start, stream, length)` escribe en bloques de 1 MiB en `start`, calcula el hash mientras escribe, hace `flush` y `os.fsync`, y devuelve el hash.
  - Hecho cuando: un test escribe el fragmento 2 de un fichero de 3 fragmentos y comprueba que solo cambian los bytes de esa posición, que el hash devuelto coincide con `hashlib` y que `os.fsync` se llamó (simulado).

- [x] **T35 — Errores del sistema de ficheros**
  - RF/RNF: caso «destino sin permisos», RNF3
  - Depende de: T33, T34
  - Traduce `OSError` (permisos, disco lleno) a `FilesystemError` (código 10) en `storage`.
  - Hecho cuando: tests con un directorio de solo lectura y con un `OSError(ENOSPC)` simulado comprueban que se lanza `FilesystemError` con mensaje traducible.

---

## Fase 7 — Fichero de estado

- [x] **T36 — Modelo del estado y serialización**
  - RF/RNF: RF8
  - Depende de: T18
  - `state.py`: dataclass con `state_version`, `manifest_id`, `destination`, `chunk_states` (`P`/`C`/`F`) y `status`; `new_state(manifest, destination)` con todos los fragmentos en `P`; `to_json`/`from_json`.
  - Hecho cuando: tests comprueban que el estado nuevo tiene un carácter por fragmento, todos `P`, `status = in_progress`, que contiene la ruta de destino y que la ida y vuelta conserva los datos.

- [x] **T37 — Validación del estado**
  - RF/RNF: RF8
  - Depende de: T36
  - Hecho cuando: tests comprueban que `StateInvalidError` (13) se lanza con: JSON inválido, `state_version` desconocida, longitud de `chunk_states` distinta del nº de fragmentos, carácter fuera de `P`/`C`/`F` y `status` desconocido.

- [x] **T38 — Clave del estado**
  - RF/RNF: RF8, RF1.4
  - Depende de: T36
  - `state_key(manifest_id, destination)` según la sección 5 (32 hex de `sha256`).
  - Hecho cuando: tests comprueban que es determinista, tiene 32 caracteres hexadecimales, cambia si cambia el manifest o el destino, y que el destino se normaliza a ruta absoluta.

- [x] **T39 — Guardado y carga atómicos**
  - RF/RNF: RF8, RF9, D8
  - Depende de: T37, T38, T35
  - Escribe `<state_key>.json.tmp`, `fsync`, `os.replace` y `fsync` del directorio; carga validando.
  - Hecho cuando: tests comprueban la ida y vuelta, que no queda `.tmp` tras guardar, y que si `os.replace` falla (simulado) el estado anterior sigue intacto y legible.

- [x] **T40 — Directorio de estado**
  - RF/RNF: RF8, RF1.4, caso «directorio de estado inaccesible»
  - Depende de: T39, T10
  - Crea el directorio si no existe y respeta `--state-dir`.
  - Hecho cuando: tests comprueban que se crea el directorio por defecto bajo un `XDG_STATE_HOME` de prueba, que se usa uno indicado explícitamente y que uno no escribible lanza `FilesystemError` (10).

- [x] **T41 — Bloqueo de descarga**
  - RF/RNF: caso «dos descargas simultáneas», D10
  - Depende de: T40
  - Bloqueo con `fcntl.flock(LOCK_EX | LOCK_NB)` sobre `<state_key>.lock`, utilizable con `with`.
  - Hecho cuando: un test abre dos bloqueos para la misma clave y el segundo lanza `AlreadyRunningError` (12); tras liberar el primero, el segundo se adquiere.

- [x] **T42 — Actualizar el estado de un fragmento**
  - RF/RNF: RF9
  - Depende de: T39
  - `set_chunk_state(state, id, char)` y guardado inmediato.
  - Hecho cuando: un test marca el fragmento 1 como `C` y el 2 como `F`, vuelve a cargar el fichero desde disco y comprueba `P C F …`; un `id` fuera de rango lanza un error.

---

## Fase 8 — Orquestación de la descarga

- [x] **T43 — Resolver el manifest de la descarga (ruta o URL)**
  - RF/RNF: RF6, RF7
  - Depende de: T18, T27
  - `downloader.py`: distingue ruta local de URL `http(s)` por esquema y devuelve un `Manifest` validado.
  - Hecho cuando: tests comprueban que una ruta y una URL (servidor de pruebas) devuelven manifests iguales, y que una URL con 404 lanza `SourceError` (3) y un contenido que no es un manifest lanza `ManifestInvalidError` (5).

- [x] **T44 — Guardar un manifest recibido como fichero local**
  - RF/RNF: RF6, D5
  - Depende de: T43, T10, T04
  - `manifest.py`: función que recibe los bytes ya validados y escribe el manifest directamente en la ruta local (por defecto `./<name>.chunkget.manifest`, o la ruta indicada), sin fichero intermedio. Si la ruta existe con contenido idéntico no hace nada; si difiere y no hay `overwrite`, lanza `OutputExistsError`; si hay `overwrite`, lo reemplaza. Un `OSError` se traduce a `FilesystemError` (código 10).
  - Hecho cuando: tests comprueban: se crea el fichero con los mismos bytes que el original y `load_manifest_file` lo carga igual; con contenido idéntico no se reescribe (la fecha de modificación no cambia) ni se lanza error; con contenido distinto y sin `overwrite` se lanza `OutputExistsError` y el fichero queda intacto; con `overwrite` se reemplaza; en un directorio de solo lectura se lanza `FilesystemError` (10); y con bytes de un manifest inválido no se crea ningún fichero.

- [ ] **T45 — Guardar el manifest en el flujo de `download`**
  - RF/RNF: RF6, RF7
  - Depende de: T44
  - `downloader.py`: cuando la fuente del manifest es una URL, valida los bytes recibidos, los guarda con T44 y continúa la descarga con el manifest validado en memoria; si la fuente es una ruta local, no escribe ningún manifest. Acepta los parámetros `manifest_file` y `overwrite_manifest`, y emite un evento con la ruta guardada.
  - Hecho cuando: tests con el servidor de pruebas comprueban: tras resolver una URL existe el fichero local y el servidor recibió una sola petición del manifest; con una ruta local no se crea ningún fichero nuevo; con la misma URL repetida no se lanza `OutputExistsError`; con un fichero local distinto en la ruta por defecto se lanza `OutputExistsError` salvo `overwrite_manifest=True`.

- [ ] **T46 — Decisión de escenario destino/estado (función pura)**
  - RF/RNF: RF7, RF8, D14
  - Depende de: T36
  - Dado si existen destino y estado, su tamaño, `restart` y `overwrite`, devuelve el escenario: `new`, `new_discarding_state`, `needs_confirmation`, `resume`, `inconsistent`.
  - Hecho cuando: un test parametrizado cubre las cinco filas de la tabla de D14 y el efecto de `restart`.

- [ ] **T47 — Aplicar el escenario**
  - RF/RNF: RF7, RF8, D14
  - Depende de: T46, T33, T40, T41
  - Prepara destino y estado según el escenario: crea ambos en `new`; descarta el estado en `new_discarding_state`; lanza `DestinationExistsError` en `needs_confirmation` si no hay `overwrite`; lanza `StateInvalidError` en `inconsistent`; carga el estado en `resume`.
  - Hecho cuando: tests comprueban, para cada escenario, el contenido de disco resultante (tamaño del destino, estado en `P`, o estado cargado) y las excepciones correspondientes.

- [ ] **T48 — Descargar un fragmento**
  - RF/RNF: RF7, RF9
  - Depende de: T29, T34, T05
  - Pide el rango, lo escribe en su posición y compara el hash con el del manifest. Devuelve: correcto, hash incorrecto o fallo reintentable de red.
  - Hecho cuando: tests contra el servidor comprueban los tres resultados (datos correctos, bytes corruptos en el fragmento, conexión cortada a mitad) y que un hash incorrecto no lanza excepción.

- [ ] **T49 — Una pasada sobre los fragmentos**
  - RF/RNF: RF9, D7
  - Depende de: T48, T42
  - Recorre los fragmentos que no están en `C`, actualiza el estado tras cada uno (`C` o `F`), continúa tras un hash incorrecto y emite eventos. Corta la pasada tras 3 fallos de red consecutivos.
  - Hecho cuando: tests comprueban que: un fragmento corrupto queda `F` y los siguientes se descargan; el estado en disco se actualiza tras cada fragmento (comprobado leyendo el fichero entre fragmentos); y con la red caída la pasada termina tras 3 fallos dejando el resto en `P`.

- [ ] **T50 — Pasadas de reintento**
  - RF/RNF: RF10, D7
  - Depende de: T49
  - Repite sobre `F`/`P` hasta `max_retries` pasadas, con la espera `min(2×2^(n−1), 60)` s mediante una función de pausa inyectable.
  - Hecho cuando: tests comprueban que: un fragmento que falla una vez y luego se sirve bien termina en `C`; las esperas solicitadas son 2, 4, 8, 16, 32; con un fragmento siempre corrupto se lanza `RetriesExhaustedError` (7) tras exactamente 1 pasada inicial + 5 de reintento, con el nº de fragmentos fallidos en el mensaje; y con `max_retries=0` no hay reintentos.

- [ ] **T51 — Validación del hash global**
  - RF/RNF: RF11
  - Depende de: T50, T12
  - Con todos los fragmentos en `C`, calcula el hash del fichero y lo compara con `global_hash`. Éxito → `status = completed`; fallo → `status = global_check_failed` y `GlobalHashMismatchError` (8).
  - Hecho cuando: tests comprueban ambos caminos y el valor de `status` leído desde disco; para el fallo se usa un manifest con `global_hash` alterado y los fragmentos correctos.

- [ ] **T52 — Reanudación**
  - RF/RNF: RF8, HU-4, criterio «se reanuda»
  - Depende de: T51, T47
  - Hecho cuando: un test descarga con un servidor que corta tras 2 de 5 fragmentos, vuelve a lanzar la descarga y comprueba, con el registro del servidor, que solo se piden los 3 fragmentos pendientes, y que el fichero final es idéntico al original.

- [ ] **T53 — Descarga ya completada**
  - RF/RNF: RF11, D14
  - Depende de: T52
  - Hecho cuando: un test repite una descarga terminada y comprueba que el servidor no recibe peticiones de fragmentos, que se verifica el hash global y que termina sin error.

- [ ] **T54 — Servidor incompatible: abortar antes de escribir datos**
  - RF/RNF: RF7, RF9, código 11
  - Depende de: T52
  - Hecho cuando: tests con servidor que ignora `Range` (200) y con servidor que devuelve otro total comprueban `ServerIncompatibleError` (11) y que el destino conserva exclusivamente ceros (ningún dato escrito) y el estado sigue en `P`.

- [ ] **T55 — Interrupción del usuario**
  - RF/RNF: caso «Ctrl-C», D8, D9
  - Depende de: T52
  - Hecho cuando: un test lanza `InterruptedByUser` desde el *listener* tras el fragmento 2; el estado en disco muestra los fragmentos 0–2 en `C` y los demás en `P`; una nueva ejecución completa la descarga y solo pide los fragmentos 3 en adelante.

- [ ] **T56 — Corte de red a mitad de fragmento**
  - RF/RNF: caso «corte de red», RF10
  - Depende de: T52
  - Hecho cuando: un test con corte a mitad del fragmento 1 comprueba que ese fragmento queda `F`, que los demás se descargan, y que en la pasada de reintento se descarga correctamente y el fichero final es idéntico.

- [ ] **T57 — Ficheros vacíos y menores que un fragmento**
  - RF/RNF: caso «fichero vacío o menor que un fragmento»
  - Depende de: T52
  - Hecho cuando: tests comprueban que una descarga con `size = 0` crea un fichero vacío y valida el hash global sin pedir fragmentos, y que un fichero menor que `chunk_size` se descarga con una única petición.

- [ ] **T58 — `restart` y estado obsoleto**
  - RF/RNF: RF8, D14
  - Depende de: T52
  - Hecho cuando: tests comprueban que `restart=True` descarta el estado y vuelve a descargar todos los fragmentos, y que un estado cuyo destino ya no existe se descarta con un evento de aviso y se hace una descarga nueva.

- [ ] **T59 — Sin ficheros temporales**
  - RF/RNF: RF7, criterio de finalización 2, constitución §5
  - Depende de: T52
  - Hecho cuando: un test lista el directorio de destino antes, durante (desde el *listener*) y después de una descarga y comprueba que solo existe el fichero destino; en el directorio de estado solo hay `<key>.json` y `<key>.lock`, sin copias del contenido ni `.tmp` residual.

---

## Fase 9 — Generación del manifest (orquestación)

- [ ] **T60 — `make-manifest` desde fichero local: escritura**
  - RF/RNF: RF2
  - Depende de: T21, T18, T10
  - `publisher.py`: construye el manifest y lo escribe en la ruta de salida (por defecto `./<name>.chunkget.manifest`) al final del proceso.
  - Hecho cuando: un test genera un manifest de un fichero con la URL dada y `load_manifest_file` lo carga con los hashes correctos.

- [ ] **T61 — Sobrescritura del manifest de salida**
  - RF/RNF: RF5
  - Depende de: T60, T04
  - Si existe y no hay `overwrite`, lanza `OutputExistsError`. Con `overwrite=True` lo trunca y escribe como si no existiera. La escritura se hace al final, tras calcular todo.
  - Hecho cuando: tests comprueban: sin `overwrite` el fichero existente no cambia; con `overwrite` se reemplaza; y si el cálculo falla (origen ilegible a mitad), el manifest anterior queda intacto.

- [ ] **T62 — Errores del origen local**
  - RF/RNF: RF4
  - Depende de: T60
  - Hecho cuando: tests comprueban `SourceError` (3) para: ruta inexistente, directorio, sin permiso de lectura; y que no se crea ningún fichero de salida.

- [ ] **T63 — Origen remoto: descargar o usar fichero local**
  - RF/RNF: RF3
  - Depende de: T61, T31
  - Con una URL de origen: o descarga el fichero a la ruta indicada (con `simple_download`) o usa un fichero local indicado; después genera el manifest como en RF2, con `url` igual a la URL de origen y `name` igual al nombre base del fichero local.
  - Hecho cuando: tests con el servidor comprueban ambos caminos y que el manifest resultante tiene `url` = la del servidor, `name` correcto y los hashes de los bytes servidos.

- [ ] **T64 — Errores del origen remoto**
  - RF/RNF: RF4
  - Depende de: T63
  - Hecho cuando: tests comprueban `SourceError` (3) para: 404, host que no resuelve, timeout y esquema no permitido; y que no queda manifest de salida.

---

## Fase 10 — Interfaz de línea de comandos

- [ ] **T65 — Esqueleto de la CLI**
  - RF/RNF: RNF3, RNF4
  - Depende de: T04, T06
  - `cli.py` con `main(argv) -> int`, subcomandos `make-manifest` y `download`, `--version`, `-h`. `__main__.py` llama a `sys.exit(main())`.
  - Hecho cuando: `tests/test_cli_basic.py` comprueba que `main(["--version"])` imprime `chunkget <versión>` en stdout y devuelve 0, que sin subcomando devuelve 2, y que `python3 -m chunkget --version` funciona en un subproceso.

- [ ] **T66 — Gestión de errores en la CLI**
  - RF/RNF: RNF3
  - Depende de: T65
  - Captura `ChunkgetError` e imprime `chunkget: error: <mensaje>` en stderr; devuelve su código. Cualquier otra excepción devuelve 1.
  - Hecho cuando: tests con comandos que lanzan cada excepción (simuladas) comprueban código, línea exacta en stderr, stdout vacío, y que una excepción inesperada devuelve 1.

- [ ] **T67 — Validación de opciones compartidas**
  - RF/RNF: RF1.2, RF1.3
  - Depende de: T66, T09, T11
  - Conecta `--chunk-size`, `--algorithm`, `--max-retries` y `--timeout` con los validadores.
  - Hecho cuando: tests comprueban que: `--algorithm md5` termina con 2 y el mensaje lista los algoritmos válidos; `--chunk-size 0` y `--max-retries 101` terminan con 2 e indican el rango; y sin opciones se usan los valores por defecto.

- [ ] **T68 — `make-manifest` con origen local**
  - RF/RNF: RF2
  - Depende de: T67, T60
  - Con `--url` genera sin preguntar; sin `--url` solicita la URL como último paso (stdin simulada) y la vuelve a pedir si es vacía o inválida; sin terminal ni `--url` termina con 2. Imprime `Manifest written: <ruta>` en stdout.
  - Hecho cuando: tests comprueban los cuatro caminos (con `--url`, URL pedida, URL inválida seguida de válida, sin terminal) y que la pregunta aparece en stderr.

- [ ] **T69 — `make-manifest`: sobrescritura**
  - RF/RNF: RF5
  - Depende de: T68, T61
  - Pregunta si desea sobrescribir; `-y` responde sí; si la respuesta es no o no hay terminal, código 4.
  - Hecho cuando: tests comprueban respuesta afirmativa (fichero reemplazado), negativa (código 4 y fichero intacto), `-y`, y ausencia de terminal (código 4).

- [ ] **T70 — `make-manifest` con origen URL**
  - RF/RNF: RF3
  - Depende de: T68, T63
  - Pregunta «descargar o usar fichero local», pide la ruta correspondiente, y admite `--download-to` y `--local-file`. `--url` con un origen URL termina con 2. Avisa de que la descarga no se puede validar.
  - Hecho cuando: tests comprueban los dos caminos interactivos, los dos flags, el error de `--url` con origen URL y la presencia del aviso en stderr.

- [ ] **T71 — `make-manifest`: errores de origen**
  - RF/RNF: RF4
  - Depende de: T68, T64
  - Hecho cuando: tests comprueban código 3, mensaje en stderr y ausencia de fichero de salida para: fichero inexistente, URL con 404 y URL que no resuelve.

- [ ] **T72 — `download`: ejecución y progreso**
  - RF/RNF: RF6, RF7, RF9
  - Depende de: T67, T52
  - Convierte los eventos en líneas de progreso en stderr (formato de 7.4), con reescritura de línea solo en terminal; imprime `Download completed: <ruta>` en stdout y `Global hash verified (<alg>).` en stderr. Con un manifest por URL imprime antes `Manifest saved: <ruta>` en stdout.
  - Hecho cuando: un test descarga contra el servidor y comprueba stdout, stderr (líneas de progreso con `chunk i/n`), código 0 y fichero idéntico al original; y otro, con el manifest servido por URL, comprueba la línea `Manifest saved: <ruta>` y que el fichero existe.

- [ ] **T73 — `download`: preguntas y opciones**
  - RF/RNF: RF6, RF7, RF8, D14
  - Depende de: T72, T47, T45
  - Atiende `DestinationExistsError` y `OutputExistsError` (manifest descargado distinto del existente) preguntando si se sobrescribe; `-y`; sin terminal → código 4. Soporta `-o`, `--state-dir`, `--manifest-file` y `--restart`. `--manifest-file` con un `MANIFEST` que es ruta local → código 2.
  - Hecho cuando: tests comprueban: destino existente sin estado con respuesta sí/no/`-y`/sin terminal; manifest local distinto en la ruta por defecto con respuesta sí/no/`-y`/sin terminal; `-o` cambia el destino; `--state-dir` coloca ahí el estado; `--manifest-file` guarda el manifest en esa ruta; `--manifest-file` con ruta local termina con 2; `--restart` repite la descarga.

- [ ] **T74 — `download`: errores finales**
  - RF/RNF: RF10, RF11, RNF3
  - Depende de: T72
  - Muestra los mensajes de 7.4 para reintentos agotados (código 7) y fallo del hash global (código 8), y el resto de códigos de 7.5 propios de `download` (3, 5, 6, 9, 10, 11, 12, 13).
  - Hecho cuando: tests con el servidor de pruebas comprueban código y mensaje en stderr para cada uno de esos códigos.

- [ ] **T75 — Señales**
  - RF/RNF: caso «Ctrl-C», D9
  - Depende de: T72, T55
  - La CLI convierte `SIGINT` y `SIGTERM` en `InterruptedByUser` y devuelve 130 y 143.
  - Hecho cuando: un test envía `SIGINT` y otro `SIGTERM` al propio proceso durante una descarga lenta (servidor con retraso) y comprueba los códigos 130 y 143 y que el estado en disco es consistente.

- [ ] **T76 — Todos los mensajes pasan por `gettext`**
  - RF/RNF: RNF2, constitución §6
  - Depende de: T74, T70
  - Hecho cuando: un test inyecta una traducción que antepone `«T»` a cada cadena traducida y ejecuta los flujos de las tareas T65–T74; comprueba que toda línea de stdout/stderr que no sea una ruta, un número o un nombre propio empieza por `«T»`.

---

## Fase 11 — Traducciones, integración y cierre

- [ ] **T77 — Plantilla y catálogo `es`**
  - RF/RNF: RNF2, D11
  - Depende de: T76
  - `locale/chunkget.pot` con `xgettext` (paquete `gettext` de jammy) y `locale/es/LC_MESSAGES/chunkget.po` con las cadenas traducidas.
  - Hecho cuando: `msgfmt --check -o /dev/null` sobre el `.po` termina con 0, y un test comprueba que cada cadena del `.pot` aparece en el `.po`.

- [ ] **T78 — Búsqueda del catálogo**
  - RF/RNF: RNF2, D11
  - Depende de: T77
  - `i18n.py` busca `locale/` junto al paquete y luego `/usr/share/locale`.
  - Hecho cuando: un test con un `.mo` de prueba (generado con `msgfmt` en el propio test) bajo un `localedir` temporal comprueba que `LANGUAGE=es` muestra la traducción, y que sin catálogo se muestra el inglés.

- [ ] **T79 — Prueba de extremo a extremo: generar y descargar**
  - RF/RNF: RF2, RF6, RF7, RF9, RF11, criterios 1 y 2
  - Depende de: T76
  - Hecho cuando: un test usa solo la CLI (`main`) contra el servidor de pruebas: `make-manifest` sobre un fichero de pocos MiB con fragmentos pequeños, luego `download` con la URL de ese manifest servida por el mismo servidor, y comprueba fichero idéntico al original (`sha256`) y que no hay ficheros temporales.

- [ ] **T80 — Prueba de extremo a extremo: interrupción y reanudación**
  - RF/RNF: RF8, RF10, criterio 3
  - Depende de: T79, T75
  - Hecho cuando: un test interrumpe `download` con el servidor cortando a mitad, repite el comando y comprueba, con el registro de peticiones, que solo se descargó lo pendiente, y que un fragmento corrupto persistente termina con código 7 sin perder los fragmentos correctos.

- [ ] **T81 — Prohibición de APIs posteriores a Python 3.10**
  - RF/RNF: RNF1, D12
  - Depende de: T06
  - Extiende `test_architecture.py`: busca en `chunkget/` usos de `tomllib`, `hashlib.file_digest`, `datetime.UTC`, `ExceptionGroup`, `typing.Self` y `match` sobre sintaxis no disponible en 3.10.
  - Hecho cuando: el test pasa con el código actual y un fichero de prueba con `import tomllib` es detectado por el mismo analizador.

- [ ] **T82 — Ejecución en entorno jammy**
  - RF/RNF: RNF1, D12, constitución §2
  - Depende de: T80, T81, T78
  - Hecho cuando: `pytest -q` pasa completo en un entorno Ubuntu jammy con `python3` 3.10 y `python3-pytest` de los repositorios oficiales; se anotan en el informe las versiones obtenidas con `python3 --version` y `pytest --version`, y se comprueba que no se instaló nada con `pip`.

- [ ] **T83 — Revisión de cobertura de requisitos**
  - RF/RNF: todos
  - Depende de: T82
  - Hecho cuando: cada RF y RNF de la tabla siguiente tiene todas sus tareas marcadas, y las desviaciones entre código, spec y plan, si las hay, están corregidas en ese orden.

---

## Cobertura de requisitos

| Requisito | Tareas |
|---|---|
| RF1.1 | T11–T18, T19, T36 |
| RF1.1.1 | T13 |
| RF1.2 | T07, T21, T67 |
| RF1.3 | T08, T09, T11, T21, T67 |
| RF1.4 | T07, T10, T38, T40 |
| RF2 | T19–T21, T60, T68, T79 |
| RF3 | T30, T31, T63, T70 |
| RF4 | T18, T25, T27, T62, T64, T71 |
| RF5 | T61, T69 |
| RF6 | T27, T43, T44, T45, T72, T73, T79 |
| RF7 | T28, T29, T33, T34, T47, T48, T54, T59, T72, T73, T79 |
| RF8 | T36–T42, T47, T52, T58, T73, T80 |
| RF9 | T34, T42, T48, T49, T72 |
| RF10 | T50, T56, T74, T80 |
| RF11 | T51, T53, T74, T79 |
| RNF1 | T01, T81, T82 |
| RNF2 | T03, T04, T76, T77, T78 |
| RNF3 | T02, T04, T66, T74 |
| RNF4 | T05, T06, T65 |
| Caso «no hay espacio» | T32 |
| Caso «manifest corrupto» | T14–T18 |
| Caso «fichero vacío o menor que un fragmento» | T17, T20, T57 |
| Caso «corte de red a mitad de fragmento» | T23, T49, T56 |
| Caso «Ctrl-C» | T55, T75 |
| Criterio 1 (manifest correcto) | T21, T60, T79 |
| Criterio 2 (descarga idéntica, sin temporales salvo estado) | T59, T79 |
| Criterio 3 (reanudación) | T52, T80 |
| Criterio 4 (errores con código y mensaje traducible) | T66, T74, T76 |
