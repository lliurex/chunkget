# Plan 001 — Implementación del MVP de chunkget

Este plan detalla **cómo** se implementa lo definido en `spec.md` (constitución §1). Si el código diverge de la spec o de este plan, se corrige primero la spec, luego el plan y finalmente el código (constitución §3).

Convenciones:
- «RFx» / «RNFx» remiten a los requisitos de `spec.md`. Cada sección indica entre corchetes los requisitos que cubre.
- Identificadores, comentarios y mensajes al usuario van en inglés (constitución §6). Este documento está en español.
- Este plan no contiene código; solo estructura, formatos y contratos.

---

## 1. Cumplimiento de la constitución

| Art. | Cómo se cumple en este plan |
|---|---|
| §1 Spec-Driven | `spec.md` define el qué; este `plan.md` define el cómo (secciones 3 a 9). |
| §2 Stack | Solo `python3` (3.10) y su biblioteca estándar en tiempo de ejecución. Desarrollo: `python3-pytest` y `python3-setuptools`, ambos de los repositorios de jammy. Compilación de catálogos: `gettext` (`msgfmt`), también de jammy. No se usan dependencias de `pip` ni YAML (ver D1). |
| §3 spec + plan antes del código | Este fichero existe antes de escribir código. |
| §4 Tests | Sección 9. Los tests usan solo un servidor HTTP en `127.0.0.1`, nunca red externa. |
| §5 Persistencia sin temporales | Se escribe directamente sobre el fichero final. El único fichero auxiliar es el de estado, que no contiene copia del contenido (D8). El manifest remoto se lee en memoria (D5). |
| §6 Idiomas | Todo en inglés. Los mensajes pasan por `gettext` (D11). |
| §7 y §8 Git | El código vive en `master`. Los parches por release van en una rama `jammy`/`noble`. El empaquetado Debian (`debian/`) **no** se incluye en `master`; vive en `debian/jammy` (fuera del alcance de este plan). |

---

## 2. Valores por defecto y rutas [RF1.2, RF1.3, RF1.4, RNF3]

Todos los valores se definen en un único módulo (`config`) y son sobrescribibles desde la CLI.

| Opción | Valor por defecto | Valores válidos | Opción CLI |
|---|---|---|---|
| Tamaño de fragmento | 100 MiB | Entero ≥ 1 B y ≤ 1 GiB. Se admiten sufijos `K`, `M`, `G` (potencias de 1024). | `--chunk-size` |
| Algoritmo de hash | `sha256` | `sha256`, `sha384`, `sha512`, `sha3_256`, `sha3_512` | `--algorithm` |
| Reintentos de fragmentos fallidos | 5 | Entero entre 0 y 100 | `--max-retries` |
| Timeout de red por operación | 30 s | Entero entre 1 y 3600 | `--timeout` |
| Espera entre pasadas de reintento | 2 s × 2^(n−1), máximo 60 s | No configurable | — |
| Fallos de red consecutivos que abortan una pasada | 3 | No configurable | — |
| Tamaño del búfer de lectura/escritura | 1 MiB | No configurable | — |
| Tamaño máximo de un fichero manifest | 64 MiB | No configurable | — |
| Número máximo de fragmentos por manifest | 250 000 | No configurable | — |
| Directorio de estado | `$XDG_STATE_HOME/chunkget/`; si no está definida, `~/.local/state/chunkget/` | Ruta | `--state-dir` |
| Fichero manifest de salida | `./<name>.chunkget.manifest` | Ruta | `-o/--output` |
| Fichero de destino de la descarga | `./<name>` (campo `name` del manifest) | Ruta | `-o/--output` |

Rutas del sistema (RF1.4):
- Estado: `<directorio de estado>/<state_key>.json`.
- Bloqueo: `<directorio de estado>/<state_key>.lock`.
- Catálogos de traducción: `locale/<lang>/LC_MESSAGES/chunkget.mo`, buscados primero junto al paquete y después en `/usr/share/locale`.

Valores no soportados (RF1.3): la CLI termina con código **2** y un mensaje que indica el valor inválido y los valores válidos (lista de algoritmos, rango de números, formato de sufijos).

---

## 3. Estructura de módulos [RNF4, RNF1, RNF2]

Disposición plana, con `conftest.py` vacío en la raíz para que `pytest -q` encuentre el paquete con pytest 6.2 de jammy (que no tiene la opción `pythonpath`).

```
chunkget/                 repositorio
├── conftest.py           hace importable el paquete en los tests
├── pyproject.toml        solo [build-system] (setuptools 59 de jammy)
├── setup.cfg             metadatos y entry point  chunkget = chunkget.cli:main
├── locale/               plantilla .pot y catálogos .po
├── chunkget/
│   ├── __init__.py       versión
│   ├── __main__.py       python3 -m chunkget
│   ├── cli.py            ÚNICO módulo que usa argparse, stdin/stdout/stderr, señales
│   ├── config.py         valores por defecto y rutas
│   ├── errors.py         ExitCode y jerarquía de excepciones
│   ├── i18n.py           inicialización de gettext
│   ├── events.py         eventos de progreso (datos)
│   ├── hashing.py        registro de algoritmos y hash en streaming
│   ├── manifest.py       modelo, (de)serialización y validación
│   ├── manifest_builder.py   genera un manifest desde un fichero local
│   ├── http.py           cliente HTTP (rangos, descarga simple, lectura en memoria)
│   ├── storage.py        destino: espacio, preasignación, escritura por offset
│   ├── state.py          fichero de estado, clave, bloqueo, guardado atómico
│   ├── downloader.py     orquestación de la descarga
│   └── publisher.py      orquestación de make-manifest (origen local o remoto)
└── tests/
```

### 3.1 Responsabilidades

| Módulo | Responsabilidad | RF/RNF |
|---|---|---|
| `cli.py` | Parsear argumentos, hacer las preguntas al usuario, mostrar progreso y errores, traducir `ExitCode` a código de salida, instalar manejadores de señal. | RF2–RF6, RF1.3, RNF3, RNF4 |
| `config.py` | Constantes por defecto, validadores de rangos y cálculo de rutas por defecto. | RF1.2, RF1.3, RF1.4 |
| `errors.py` | Enumeración `ExitCode` y excepciones con mensaje traducible y código asociado. | RNF2, RNF3 |
| `i18n.py` | `gettext` (`_`, `ngettext`) con dominio `chunkget`. | RNF2 |
| `events.py` | Dataclasses de eventos (`ChunkDone`, `PassStarted`, `GlobalCheckStarted`…) que el núcleo envía a un *listener* opcional. | RNF4 |
| `hashing.py` | Algoritmos soportados, formato `alg:hex`, hash en streaming de ficheros y de flujos. | RF1.1, RF1.3, RF9, RF11 |
| `manifest.py` | Modelo `Manifest`/`Chunk`, carga desde bytes, volcado a JSON, validación completa. | RF1.1, RF1.1.1, RF6, caso «manifest corrupto» |
| `manifest_builder.py` | Calcular en una sola lectura los hashes de fragmento y el global. | RF2, RF3 |
| `http.py` | Abrir URLs http/https, pedir rangos, validar `206`/`Content-Range`, clasificar errores, leer un recurso pequeño en memoria, descarga simple con reanudación. | RF3, RF4, RF6, RF7, RF9, RF10 |
| `storage.py` | Comprobar espacio, crear/preasignar el fichero final, escribir un fragmento en su posición, volcar a disco, releer para el hash global. | RF7, RF11, caso «sin espacio» |
| `state.py` | Modelo del estado, `state_key`, carga/guardado atómico, bloqueo exclusivo. | RF8, RF9, caso «Ctrl-C» |
| `downloader.py` | Flujo completo de `download`: preparar, pasadas, reintentos, hash global. | RF6–RF11 |
| `publisher.py` | Flujo de `make-manifest`: origen local o remoto, generación y escritura del manifest. | RF2–RF5 |

### 3.2 Reglas de dependencia (RNF4)
- `cli.py` importa el resto; **ningún otro módulo importa `cli.py`**.
- Solo `cli.py` importa `argparse`, lee `sys.argv`, usa `input()`/`sys.stdout`/`sys.stderr`, llama a `sys.exit` o instala señales. El núcleo nunca imprime.
- Dependencias internas permitidas: `downloader` y `publisher` → (`manifest`, `manifest_builder`, `http`, `storage`, `state`, `hashing`, `config`, `errors`, `events`). Los módulos de bajo nivel no se importan entre sí salvo `manifest` → `hashing` y `storage`/`state` → `errors`.

### 3.3 Comunicación núcleo → CLI (RNF4)
- **Preguntas al usuario:** el núcleo no pregunta. Recibe decisiones ya resueltas como parámetros explícitos (por ejemplo `overwrite=True`). Si falta una decisión, lanza una excepción específica (`OutputExistsError`, `DestinationExistsError`) y la CLI pregunta y vuelve a llamar con el parámetro.
- **Progreso:** el núcleo acepta un *listener* opcional que recibe objetos de `events.py`.
- **Errores:** toda excepción del núcleo es subclase de `ChunkgetError` y lleva su `ExitCode` y un mensaje ya traducido con `gettext`.

---

## 4. Modelo del manifest [RF1.1, RF1.1.1, RF6, RNF3, caso «manifest corrupto»]

Formato: **JSON** UTF-8, indentado y con claves en orden fijo, para que sea legible por una persona (RF1.1.1, D1). Las claves están en inglés.

### 4.1 Campos de primer nivel [RF1.1]

| Clave | Tipo | Significado | Requisito |
|---|---|---|---|
| `protocol_version` | entero | Versión del formato del manifest. Valor actual: `1`. | «versión del protocolo» |
| `name` | texto | Nombre del fichero (solo nombre base, sin ruta). | «nombre del fichero» |
| `url` | texto | URL `http://` o `https://` desde la que se descarga. | «campo url» |
| `size` | entero ≥ 0 | Tamaño total en bytes. | «tamaño del fichero» |
| `chunk_size` | entero ≥ 1 | Tamaño máximo de fragmento en bytes. | «tamaño máximo del fragmento» |
| `global_hash` | texto | Hash de todo el fichero, en formato `algoritmo:hex`. | «hash global» |
| `chunks` | lista | Fragmentos, ordenados por `id`. | «listado de fragmentos» |

### 4.2 Elementos de `chunks` [RF1.1]

| Clave | Tipo | Significado |
|---|---|---|
| `id` | entero | Identificador, igual a la posición en la lista (0, 1, 2…). |
| `start` | entero | Posición inicial en el fichero, **inclusiva**. |
| `end` | entero | Posición final en el fichero, **exclusiva**. Longitud = `end − start`. |
| `hash` | texto | Hash del fragmento, formato `algoritmo:hex`. |

### 4.3 Formato de los hashes y algoritmo
La spec no lista un campo de algoritmo. Para no añadir campos fuera de RF1.1, **el algoritmo va dentro del propio hash** como prefijo: `sha256:3b4c…`. El algoritmo del manifest es el del prefijo de `global_hash`.

### 4.4 Invariantes que valida `manifest.py`
1. El JSON es un objeto con exactamente las claves de 4.1; los tipos coinciden.
2. `protocol_version` es un valor soportado; si es mayor, error «unsupported version»; si es menor, error «obsolete».
3. `name` no está vacío, no es `.` ni `..`, no contiene `/`, `\` ni NUL, y tiene como máximo 255 bytes en UTF-8 (evita escrituras fuera del directorio de destino).
4. `url` es `http://` o `https://` y tiene host.
5. `chunk_size` está entre 1 y 1 GiB.
6. Todos los hashes usan el **mismo algoritmo**, soportado, y su `hex` tiene la longitud exacta del algoritmo y solo dígitos hexadecimales en minúscula.
7. Número de fragmentos = `ceil(size / chunk_size)`, y es como máximo 250 000.
8. `id` es consecutivo desde 0; `chunks[0].start = 0`; cada `start` es el `end` del anterior; el último `end` es `size`; cada fragmento mide `chunk_size`, salvo el último, que mide entre 1 y `chunk_size`.
9. El fichero manifest no supera 64 MiB.

Cualquier fallo de 4.4 es «manifest corrupto o inválido» y termina con `ExitCode` 5.

### 4.5 Casos límite del modelo
- **Fichero vacío** [caso «fichero vacío»]: `size = 0`, `chunks = []`, `global_hash` = hash de la cadena vacía. La descarga crea el fichero vacío y verifica el hash global.
- **Fichero menor que un fragmento**: un único fragmento con `end = size`.
- **Último fragmento más corto**: lo cubre el invariante 8.

### 4.6 Identificador del manifest
`manifest_id` = valor de `global_hash`. Se usa en el estado (sección 5) para asociar descarga y manifest.

---

## 5. Modelo del fichero de estado [RF8, RF9, RF10, caso «Ctrl-C»]

Formato JSON UTF-8. No tiene que ser legible, pero se mantiene en JSON para poder depurarlo.

| Clave | Tipo | Significado |
|---|---|---|
| `state_version` | entero | Versión del formato del estado (actual: `1`). |
| `manifest_id` | texto | `global_hash` del manifest. |
| `destination` | texto | Ruta absoluta donde se está descargando [RF8: «la ruta donde se está descargando»]. |
| `chunk_states` | texto | Un carácter por fragmento, en orden de `id`. Ver estados. |
| `status` | texto | `in_progress`, `completed` o `global_check_failed`. |

Estados de fragmento [RF8: «los diferentes estados se definen en el plan»]:

| Carácter | Estado | Significado |
|---|---|---|
| `P` | `pending` | Aún no descargado, o descarga interrumpida a mitad. |
| `C` | `correct` | Descargado y con el hash verificado (RF9). |
| `F` | `failed` | Descargado, pero el hash no coincide, o la descarga falló (RF9, RF10). |

Reglas:
- `state_key` = primeros 32 caracteres hexadecimales de `sha256(manifest_id + "\0" + destination)`. Así hay un estado por pareja manifest + destino.
- Un fragmento solo pasa a `C` después de escribirse, volcarse a disco y verificar su hash (D6, D8).
- Un fragmento interrumpido a mitad **no** cambia de estado: queda `P` (o `F` si venía de ahí), y se vuelve a descargar entero.
- Un estado con versión desconocida, JSON inválido, longitud de `chunk_states` distinta del número de fragmentos del manifest, o carácter fuera de `P`/`C`/`F` es inconsistente: `ExitCode` 13.

---

## 6. Decisiones técnicas

### D1. Formato JSON; sin YAML [RF1.1.1]
`json` es parte de la biblioteca estándar, por lo que siempre está disponible. RF1.1.1 admite YAML solo si JSON no lo estuviera; no se implementa. En Python 3.10 no hay `tomllib`, otra razón para no usar TOML.

### D2. Algoritmos y hash en streaming [RF1.1, RF1.3, RF9, RF11, RNF2]
- Solo `hashlib` con la lista de 2. Se excluyen `md5` y `sha1`.
- Los hashes se calculan siempre en streaming con el búfer de 1 MiB; nunca se carga un fragmento completo en memoria. La memoria es constante e independiente del tamaño del fichero y del fragmento (RNF2).

### D3. Generación del manifest en una sola lectura [RF2, RF3]
Al leer el fichero una vez se actualizan a la vez el hash del fragmento actual y el global. Con ficheros de >3 GB no hay una segunda pasada. El manifest se arma en memoria y **se escribe al final**, de modo que un fallo antes de ese punto no deja un manifest parcial ni trunca uno previo (D14).

### D4. Origen remoto en `make-manifest` [RF3, RF4]
1. La CLI pregunta si se **descarga** el fichero (y a qué ruta) o si se usa un **fichero local** existente (y cuál).
2. Si se descarga, `http.py` hace una descarga simple (GET en streaming) directamente a la ruta indicada. Si la conexión se corta, reanuda con `Range` desde el tamaño ya escrito, con las mismas esperas y límite de reintentos que D7. Antes de empezar se comprueba el espacio con `Content-Length`.
3. Con el fichero ya en local se aplica el flujo de RF2. La diferencia es que `url` se rellena con la URL indicada como origen.
4. `name` es el nombre base del fichero local usado.
5. **Limitación conocida:** esa descarga no puede validarse, porque aún no existe manifest. La CLI avisa al publicador con un mensaje explícito.

### D5. Cliente HTTP con `urllib` [RF3, RF4, RF6, RF7, RF9, RF10, caso «recurso remoto»]
- Solo `urllib.request`/`http.client`. Esquemas permitidos: `http` y `https`. Un manejador de redirecciones propio rechaza cualquier otro esquema. La verificación TLS es la predeterminada.
- Cabeceras: `User-Agent: chunkget/<versión>` y `Accept-Encoding: identity`. Si la respuesta trae `Content-Encoding` distinto de `identity`, es un error de servidor incompatible (código 11).
- **Fragmento:** `Range: bytes=<start>-<end−1>`. Se exige estado `206`, `Content-Range` exacto con total igual a `size`, y longitud recibida igual a la del fragmento. Si el estado es `200` (sin rangos) o el total difiere de `size` → código 11 y se aborta **antes de escribir datos**.
- **Clasificación de errores:**

| Situación | Tratamiento |
|---|---|
| Corte de conexión, timeout, reset, `5xx`, `408`, `429` | Reintentable (D7). |
| `4xx` restantes, fallo de certificado TLS, esquema no soportado | Fatal: código 6. |
| `200` en lugar de `206`, total distinto, `Content-Encoding` | Fatal: código 11. |

- **Manifest remoto [RF6]:** se lee a un `bytes` en memoria con tope de 64 MiB y se procesa con el mismo código que un manifest local. **No se crea fichero temporal** (constitución §5).
- Las variables de entorno de proxy del sistema que `urllib` respeta se mantienen; no se implementa ninguna gestión propia de proxies (fuera de alcance).

### D6. Escritura sobre el fichero final y espacio [RF7, RF9, RF11, caso «sin espacio»]
- El destino es el único fichero con contenido (constitución §5). No se crea ningún fichero temporal ni copia.
- **Comprobación de espacio:** antes de crear o extender el destino, `shutil.disk_usage` del directorio destino debe ofrecer al menos `size − tamaño actual del destino` bytes. Si no, código 9, sin escribir nada.
- **Creación [RF7]:** se crea el fichero con el tamaño exacto del manifest; se intenta reservar los bloques con `os.posix_fallocate`. Si el sistema de ficheros no lo soporta, se usa truncado (fichero disperso) y la comprobación de espacio anterior es la única garantía.
- **Escritura de un fragmento:** se abre el destino en modo lectura-escritura, se posiciona en `start` y se escribe el flujo en bloques de 1 MiB mientras se actualiza el hash (D2). Al terminar:
  1. Se compara el hash con el del manifest.
  2. Si coincide, `flush` + `os.fsync` y **solo entonces** se actualiza el estado a `C` (D8).
  3. Si no coincide, el estado pasa a `F`; la región queda con datos incorrectos que se sobrescribirán en el reintento.
- **Aviso:** un fichero parcial tiene el nombre y el tamaño finales. El estado es la única fuente de verdad sobre su completitud; la CLI lo indica en sus mensajes.

### D7. Pasadas y reintentos [RF9, RF10, caso «corte de red»]
Algoritmo de `downloader.py`:
1. **Pasada inicial:** recorre los fragmentos que no estén en `C`, en orden.
2. Si el hash coincide → `C` y siguiente. Si no → `F` y **sigue con el siguiente** (RF9).
3. Si hay un error reintentable de red a mitad de un fragmento, el fragmento queda `F` y el contador de fallos de red consecutivos aumenta; un fragmento correcto lo pone a 0. Al llegar a 3, **la pasada termina antes de tiempo**, y los fragmentos no tratados siguen en `P`. Esto evita esperar timeouts de cada fragmento cuando no hay red.
4. **Pasadas de reintento (RF10):** al terminar una pasada, si quedan fragmentos en `F` o `P`, se espera `min(2 × 2^(n−1), 60)` segundos (n = número de reintento) y se repite sobre ellos. Se hacen como máximo `--max-retries` (por defecto **5**) pasadas de reintento, además de la inicial.
5. Si tras la última pasada quedan fragmentos sin `C`, se notifica cuántos son y se termina con código **7**, conservando el estado y los fragmentos correctos (RF10).
6. La espera usa una función de pausa inyectable para poder probarla sin retrasos.

### D8. Consistencia y durabilidad del estado [RF8, RF9, caso «Ctrl-C»]
- **Guardado atómico:** el estado se escribe a `<state_key>.json.tmp` en el mismo directorio, se hace `fsync`, `os.replace` sobre el definitivo y `fsync` del directorio. El fichero `.tmp` contiene solo metadatos, **nunca contenido del fichero descargado**, por lo que cumple la constitución §5.
- **Orden estricto:** dato escrito → `fsync` del destino → hash verificado → estado guardado. Tras un corte, un fragmento marcado `C` tiene su contenido en disco.
- Un fallo de escritura del estado o del destino (permisos, disco lleno, directorio de estado inaccesible) → código 10.
- Se guarda el estado tras **cada** fragmento (RF9: «justo después de comprobar la verificación»).

### D9. Señales y Ctrl-C [caso «Ctrl-C»]
- `cli.py` convierte `SIGINT` y `SIGTERM` en la excepción `InterruptedByUser`.
- El núcleo cierra ficheros en bloques `finally`. El fragmento en curso queda sin cambiar de estado (D8), por lo que el estado en disco es siempre el del último fragmento terminado.
- Códigos de salida: **130** (SIGINT) y **143** (SIGTERM).

### D10. Bloqueo de descargas simultáneas [caso «dos descargas»]
Se toma `fcntl.flock(LOCK_EX | LOCK_NB)` sobre `<state_key>.lock` durante toda la descarga. Si ya está tomado → código 12. El fichero `.lock` es vacío y se conserva.

### D11. Traducción con gettext [RNF2, constitución §6]
- Cadenas fuente en inglés, marcadas con `_()` / `ngettext()` (plurales en el progreso). Dominio `chunkget`.
- `locale/chunkget.pot` y catálogos `locale/<lang>/LC_MESSAGES/chunkget.po`. Los `.mo` se generan con `msgfmt` durante el empaquetado.
- `i18n.py` usa `gettext.translation(..., fallback=True)`: sin catálogo se muestra el inglés.
- Los mensajes de las excepciones del núcleo se crean ya traducidos; la CLI solo los imprime. Los mensajes propios de `argparse` usan su propio dominio estándar de Python.

### D12. Empaquetado y entorno [RNF1]
- `setup.cfg` con metadatos y `console_scripts`; `pyproject.toml` solo con `[build-system]`. No se usa la sección `[project]`, que setuptools 59 (jammy) no soporta.
- Código compatible con Python 3.10: sin `tomllib`, `hashlib.file_digest`, `datetime.UTC` ni `ExceptionGroup`. El desarrollo local puede usar otro Python, pero la validación final se hace en un entorno jammy (versiones de jammy: `python3` 3.10, `python3-pytest` 6.2.x, `python3-setuptools` 59.x; verificar con `apt-cache policy`).
- Plataforma objetivo: Linux. `fcntl` y `os.posix_fallocate` son específicos de Unix y no se soportan en otros sistemas.

### D13. Memoria acotada [RNF2]
Un único búfer de 1 MiB, el manifest en memoria (máx. 64 MiB de fichero y 250 000 fragmentos) y la cadena `chunk_states` (1 byte por fragmento). Independiente del tamaño del fichero.

### D14. Situaciones del destino y del estado [RF5, RF7, RF8, RF10, RF11]

Al iniciar `download`, tras validar el manifest y tomar el bloqueo (D10):

| Destino | Estado | Acción |
|---|---|---|
| No existe | No existe | Descarga nueva: comprobar espacio, crear destino y estado con todos los fragmentos en `P`. |
| No existe | Existe | Estado obsoleto: se descarta con un aviso y se hace descarga nueva. |
| Existe | No existe | La CLI pregunta si se sobrescribe. Si el usuario acepta (`--yes` o respuesta afirmativa) → descarga nueva sobre ese fichero; si no → código 4. |
| Existe, tamaño ≠ `size` | Existe | Inconsistente → código 13 (usar `--restart`). |
| Existe, tamaño = `size` | Existe, coincidente | **Reanudar** [RF8]: solo se tratan los fragmentos que no estén en `C`. |

- Si todos los fragmentos están en `C`, solo se hace la verificación del hash global (RF11).
- `--restart` descarta el estado y se actúa como «descarga nueva» (con la pregunta de sobrescritura si el destino existe).
- Tras el éxito, el estado **se conserva** con `status = completed`. Relanzar la misma descarga solo verifica el hash global y sale con 0.
- Si el hash global falla (RF11), el estado queda con `status = global_check_failed`, sin borrar nada.

---

## 7. Contrato de la CLI [RF1.3, RF2–RF11, RNF3, RNF4]

Ejecutable: `chunkget` (también `python3 -m chunkget`). Dos subcomandos, sin otros.

### 7.1 Opciones globales
- `-h`, `--help`: ayuda (traducida).
- `--version`: imprime `chunkget <versión>` en stdout y sale con 0.

### 7.2 Convención de salida
- **stdout:** solo el resultado final (rutas generadas, confirmación de éxito). Apto para scripts.
- **stderr:** preguntas, progreso, avisos y errores.
- Preguntas: se leen de stdin. Si stdin no es una terminal y no se pasó `--yes` ni la opción explícita equivalente, la pregunta se considera **rechazada** y se sale con código 4.
- Toda línea de texto pasa por `gettext` (constitución §6). La lengua se toma de las variables de entorno de localización.

### 7.3 `chunkget make-manifest` [RF2, RF3, RF4, RF5, RF1.2, RF1.3]

```
chunkget make-manifest SOURCE [-o OUTPUT] [--chunk-size SIZE] [--algorithm NAME]
                              [--url URL] [--download-to PATH | --local-file PATH]
                              [--timeout SECONDS] [--max-retries N] [-y]
```

| Argumento | Significado | RF |
|---|---|---|
| `SOURCE` | Fichero local o URL `http(s)`. | RF2, RF3 |
| `-o, --output` | Ruta del manifest. Defecto: `./<name>.chunkget.manifest`. | RF5, RF1.4 |
| `--chunk-size` | Tamaño de fragmento (sección 2). | RF1.2, RF1.3 |
| `--algorithm` | Algoritmo de hash (sección 2). | RF1.2, RF1.3 |
| `--url` | URL de descarga. Obligatoria **solo** con origen local en modo no interactivo; si no se da, se solicita como último paso. **Error de uso** (código 2) si se indica con un `SOURCE` URL. | RF2, RF3 |
| `--download-to PATH` | Con `SOURCE` URL: descargar el fichero a `PATH` sin preguntar. | RF3 |
| `--local-file PATH` | Con `SOURCE` URL: usar `PATH` como fichero local sin preguntar. | RF3 |
| `--timeout`, `--max-retries` | Solo afectan a la descarga de RF3 (D4). | RF3 |
| `-y, --yes` | Responde «sí» a la confirmación de sobrescritura. | RF5 |

Flujo y preguntas (siempre por stderr):
1. Origen local: se calcula el manifest (D3). Si falta la URL, se solicita **como último paso** [RF2]. Una URL vacía o inválida se vuelve a pedir; en modo no interactivo, es error de uso (2).
2. Origen URL [RF3]: pregunta «download the file or use an existing local file?». Según la respuesta se pide la ruta de descarga (si ya existe, se pide confirmación para sobrescribir) o la ruta del fichero local. `url` = `SOURCE`.
3. Si el manifest de salida existe [RF5]: pregunta «overwrite?». Si se acepta, se trunca y se escribe como si no existiera; si no, código 4. La escritura ocurre al final (D3).

Salida de éxito (stdout): `Manifest written: <ruta>`.

### 7.4 `chunkget download` [RF6, RF7, RF8, RF9, RF10, RF11, RF1.2, RF1.3]

```
chunkget download MANIFEST [-o OUTPUT] [--max-retries N] [--timeout SECONDS]
                           [--state-dir DIR] [--restart] [-y]
```

| Argumento | Significado | RF |
|---|---|---|
| `MANIFEST` | Ruta local **o** URL `http(s)` de un manifest. La URL se distingue por su esquema. | RF6, RF7 |
| `-o, --output` | Ruta del fichero destino. Defecto: `./<name>`. | RF7 |
| `--max-retries` | Pasadas de reintento de fragmentos fallidos. Defecto 5. | RF10 |
| `--timeout` | Timeout de red. | RF10 |
| `--state-dir` | Directorio del estado. Defecto: sección 2. | RF8, RF1.4 |
| `--restart` | Descarta el estado y empieza desde cero. | RF8, RF11 |
| `-y, --yes` | Acepta la sobrescritura de un destino sin estado (D14). | RF7 |

La URL de descarga se toma **siempre** del campo `url` del manifest. No existe opción para cambiarla.

Salida:
- Progreso (stderr), una línea por fragmento terminado; en terminal se reescribe la misma línea. Ejemplo: `Downloading image.iso: chunk 12/768 (1.6%), 48.0 MiB of 3.0 GiB`.
- Cuando empieza una pasada de reintento: `Retry pass 2/5: 7 chunks pending`.
- Éxito [RF11] (stdout): `Download completed: <ruta>` y, en stderr, `Global hash verified (sha256).`
- Fallo del hash global [RF11] (stderr): `Global validation failed: the file does not match the manifest hash. Use --restart to download it again.`
- Reintentos agotados [RF10] (stderr): `Download incomplete: 3 chunks still failed after 5 retry passes. Run the command again to resume.`

### 7.5 Códigos de salida [RNF3, RF4, RF5, RF10, RF11, casos límite]

| Código | Nombre | Cuándo | RF |
|---|---|---|---|
| 0 | `OK` | Éxito. | RNF3 |
| 1 | `UNEXPECTED` | Error interno no previsto. | RNF3 |
| 2 | `USAGE` | Argumentos inválidos o valor de opción no soportado (el mensaje lista los válidos). | RF1.3 |
| 3 | `SOURCE_ERROR` | El fichero de origen o el manifest no existe, no es legible o la URL da error (404, DNS, timeout, TLS…). | RF4, RF6 |
| 4 | `USER_DECLINED` | El usuario rechaza una confirmación (sobrescribir) o no se puede preguntar. | RF5, D14 |
| 5 | `MANIFEST_INVALID` | Manifest corrupto, inválido o de versión no soportada. | RF1.1, caso «manifest corrupto» |
| 6 | `NETWORK_ERROR` | Error fatal de red/HTTP al descargar (4xx no reintentable, certificado inválido). | RF7, RF9 |
| 7 | `RETRIES_EXHAUSTED` | Quedan fragmentos sin descargar tras agotar los reintentos. | RF10 |
| 8 | `GLOBAL_HASH_MISMATCH` | Fallo de la validación del hash global. | RF11 |
| 9 | `NO_SPACE` | No hay espacio suficiente para el fichero. | caso «sin espacio» |
| 10 | `FILESYSTEM_ERROR` | Error al leer/escribir el destino, el manifest o el estado (permisos, disco lleno). | RF5, RF7, RF8 |
| 11 | `SERVER_INCOMPATIBLE` | El servidor no admite rangos, el tamaño remoto no coincide con el manifest o aplica `Content-Encoding`. | RF7, RF9 |
| 12 | `ALREADY_RUNNING` | Otra descarga usa el mismo destino y manifest. | caso «dos descargas» |
| 13 | `STATE_INVALID` | Estado corrupto, de otra versión o inconsistente con el destino. | RF8 |
| 130 | `INTERRUPTED` | Interrupción por Ctrl-C (SIGINT). | caso «Ctrl-C» |
| 143 | `TERMINATED` | Interrupción por SIGTERM. | caso «Ctrl-C» |

Los mensajes de error van a stderr, en una sola línea con el formato `chunkget: error: <mensaje>`, y son siempre traducibles (RNF2).

---

## 8. Resolución de los casos límite de la spec (sección 6)

| Caso límite | Resolución | Sección |
|---|---|---|
| No hay suficiente espacio | Comprobación previa, código 9, sin escribir. | D6 |
| Manifest corrupto | Validación completa, código 5. | 4.4 |
| Fichero vacío | `size = 0`, sin fragmentos, hash global de la cadena vacía. | 4.5 |
| Fichero menor que un fragmento | Un único fragmento. | 4.5 |
| Corte de red a mitad de fragmento | Fragmento en `F`, pasada abortada tras 3 fallos seguidos, reintento con espera. | D7 |
| Ctrl-C | Estado atómico; solo cuentan los fragmentos terminados; código 130. | D8, D9 |

---

## 9. Estrategia de pruebas [constitución §4]

Todo cambio de código lleva su test. `pytest -q` debe pasar completo antes de dar una tarea por terminada.

- **Red:** solo un servidor HTTP en `127.0.0.1` con puerto efímero, implementado con `http.server`, con soporte de `Range` y fallos inyectables: corte de conexión a mitad de fragmento, bytes corruptos, ignorar `Range` (devolver 200), cambiar el tamaño total, `Content-Encoding`, errores `4xx`/`5xx`.
- **Tiempo:** la pausa entre reintentos es una función inyectable; los tests no esperan.
- **Ficheros grandes:** no se crean ficheros de varios GB. Los tests usan fragmentos de pocos bytes; el espacio se simula sustituyendo `shutil.disk_usage`.
- **Interrupción:** se simula lanzando `InterruptedByUser` desde el *listener* de progreso.
- **CLI:** se invoca `main(argv)` y se comprueban el código de salida, stdout y stderr, con stdin simulada.
- **Traducción:** un test comprueba que una cadena se traduce con un catálogo de prueba y que, sin catálogo, se muestra en inglés.
- **Núcleo sin CLI (RNF4):** un test comprueba que los módulos del núcleo no importan `argparse` ni `cli`.

| Fichero de test | Cubre |
|---|---|
| `test_manifest.py` | RF1.1, RF1.1.1, RF6, invariantes 4.4, fichero vacío, caso «manifest corrupto» |
| `test_manifest_builder.py` | RF2, RF3, equivalencia con `hashlib` externo |
| `test_publisher.py` | RF2, RF3, RF4, RF5 |
| `test_http.py` | RF3, RF6, RF7, clasificación de errores (D5) |
| `test_state.py` | RF8, RF9, guardado atómico, `state_key`, bloqueo |
| `test_storage.py` | RF7, espacio, preasignación |
| `test_downloader.py` | RF7–RF11, D7, D14, reanudación, Ctrl-C, corte de red |
| `test_config.py` | RF1.2, RF1.3, RF1.4 |
| `test_cli_make_manifest.py` | RF2–RF5, RF1.3, RNF3 |
| `test_cli_download.py` | RF6–RF11, RNF3 |
| `test_i18n.py` | RNF2 |
| `test_architecture.py` | RNF4 |

---

## 10. Matriz de cobertura de requisitos

| Requisito | Dónde se cubre |
|---|---|
| RF1.1 | Sección 4 (4.1 a 4.4), `manifest.py` |
| RF1.1.1 | Sección 4, D1 |
| RF1.2 | Sección 2, `config.py`, opciones de 7.3 y 7.4 |
| RF1.3 | Sección 2, código 2 de 7.5 |
| RF1.4 | Secciones 2 y 5 (rutas y valores por defecto) |
| RF2 | D3, 7.3 punto 1, `manifest_builder.py`, `publisher.py` |
| RF3 | D4, 7.3 punto 2, `http.py`, `publisher.py` |
| RF4 | D5, código 3 de 7.5 |
| RF5 | 7.3 punto 3, D3, D14, código 4 |
| RF6 | D5 (lectura en memoria), 7.4 (`MANIFEST` ruta o URL) |
| RF7 | D6, D14, 7.4 |
| RF8 | Sección 5, D8, D14, `state.py` |
| RF9 | D6, D7, D8, sección 5 |
| RF10 | D7, código 7 de 7.5, opción `--max-retries` |
| RF11 | D14, `storage.py` (releer para el hash), códigos 8 de 7.5 |
| RNF1 | D2, D12, sección 1 (§2) |
| RNF2 | D2, D11, `errors.py`, `i18n.py` |
| RNF3 | 7.5, `errors.py` |
| RNF4 | Secciones 3.2 y 3.3, `test_architecture.py` |
| Sección 6 de la spec | Sección 8 de este plan |
| Sección 8 de la spec (criterios) | Manifest desde fichero local o URL → D3, D4; descarga sin temporales salvo estado → D6, D8; reanudación → D7, D14; errores con código y mensaje traducible → 7.5 |

---

## 11. Decisiones no fijadas por la spec (a confirmar)

Este plan resuelve las siguientes lagunas de `spec.md`. Si alguna no es la deseada, se corrige primero la spec (constitución §3):

1. **Algoritmo dentro del hash** (prefijo `sha256:`), porque RF1.1 no incluye un campo de algoritmo (4.3).
2. **`end` exclusivo** en los fragmentos (4.2).
3. **URL obligatoria y validada** en el manifest, mientras que RF2 solo dice que «se solicitará»: no se admite vacía.
4. **Descarga de RF3 sin validación**, con aviso al publicador (D4).
5. **Reintentos reales de red**: RF10 habla de fragmentos «fallidos»; se amplía a errores de red, con aborto temprano de la pasada tras 3 fallos seguidos (D7).
6. **Pasadas de reintento con espera creciente** (2, 4, 8, 16, 32 s), que RF10 no especifica.
7. **Destino existente sin estado**: se pregunta antes de sobrescribir (D14); la spec no lo define.
8. **Estado sin destino**: se descarta y se empieza de nuevo (D14).
9. **El estado se conserva tras el éxito** (`completed`) y se añade `--restart` (D14).
10. **Servidor sin soporte de rangos o con tamaño distinto** → código 11 antes de escribir; la spec lo incluía en una versión anterior, no en la actual.
11. **Bloqueo de descargas simultáneas** con `flock` (D10).
12. **YAML no se implementa**; RF1.1.1 queda cubierto solo con JSON (D1).
13. **Subcomandos adicionales no previstos:** ninguno. La comprobación posterior de un fichero descargado (antigua spec 002) no forma parte de este MVP.
