# Spec 001 — MVP de chunkget

## 1. Contexto y objetivo
Descargar ficheros grandes (>3 GB) por conexiones inestables es frágil: un corte obliga a repetir todo y un fallo silencioso puede dejar el fichero corrupto. chunkget divide la descarga en fragmentos, valida cada uno con un hash conocido de antemano y escribe siempre sobre el fichero final (sin temporales que dupliquen el espacio). Objetivo del MVP: dos comandos, uno que genera un *manifest* describiendo un fichero y otro que lo usa para descargarlo de forma fragmentada, validada y reanudable.

## 2. Usuarios
- **Publicador**: quien dispone del fichero y lo distribuye; genera el manifest.
- **Descargador**: usuario de una distribución basada en Ubuntu con conexión inestable que necesita obtener el fichero íntegro.

## 3. Historias de usuario
- HU-1: Como publicador, quiero generar un manifest a partir de un fichero local o una URL para que otros lo descarguen con garantías.
- HU-2: Como descargador, quiero descargar el fichero a partir del manifest para que los cortes de red no me obliguen a empezar de cero.
- HU-3: Como descargador, quiero que cada fragmento se valide para tener certeza de que el fichero final es correcto.
- HU-4: Como descargador, quiero relanzar una descarga interrumpida y que solo se descargue lo pendiente.
- HU-5: Como descargador, quiero ver un progreso simple y errores claros.

## 4. Requisitos funcionales (EARS)

### Comando de generación de manifest
- RF-1: Cuando el publicador indique un fichero local como origen, el sistema deberá generar un manifest con nombre, tamaño total, una url vacia que luego completara con la url final,tamaño de fragmento, algoritmo de hash, hash de cada fragmento y hash global.
  - Aceptación: el manifest de un fichero de N bytes y fragmento F contiene ceil(N/F) hashes, y el hash global coincide con el calculado externamente.
- RF-2: Cuando el publicador indique una URL HTTP/HTTPS como origen, el sistema deberá leer el contenido remoto y generar el mismo manifest que para un fichero local idéntico.
  - Aceptación: los manifests de un fichero local y de su copia remota son equivalentes en los datos de validación.
- RF-3: Cuando el publicador indique un tamaño de fragmento o un algoritmo de hash, el sistema deberá usarlos; si no, deberá usar los valores por defecto documentados.
- RF-4: Si el algoritmo de hash solicitado no está soportado, entonces el sistema deberá terminar con error indicando los algoritmos disponibles, sin generar manifest.
- RF-5: Si el origen no existe o no es accesible, entonces el sistema deberá terminar con código de salida distinto de 0 y un mensaje claro, sin dejar manifest parcial.
- RF-6: Si el manifest de salida ya existe, entonces el sistema deberá negarse a sobrescribirlo salvo petición explícita.
- RF-7: El manifest deberá ser legible por una persona, estar versionado e incluir la URL de descarga cuando el publicador la proporcione.

### Comando de descarga
- RF-8: Cuando el descargador indique un manifest (ruta local o URL), el sistema deberá descargar el fichero por fragmentos escribiendo directamente en el fichero final.
  - Aceptación: durante y tras la descarga no existen ficheros temporales con el contenido del fichero, solo existe un.
- RF-9: Cuando se complete la descarga de un fragmento, el sistema deberá validar su hash contra el manifest antes de darlo por bueno.
- RF-10: Si un fragmento no supera la validación, entonces el sistema deberá reintentarlo hasta un máximo de N veces con espera creciente y, si persiste el fallo, abortar con código distinto de 0 conservando el progreso válido.
- RF-11: Si falla la conexión durante un fragmento, entonces el sistema deberá aplicar la misma política de reintentos que en RF-10.
- RF-12: Cuando se interrumpa una descarga, el sistema deberá haber registrado en un fichero de estado, ubicado en un directorio distinto al del fichero destino, qué fragmentos están completos.
- RF-13: Cuando el descargador relance una descarga con estado previo, el sistema deberá reanudar descargando solo los fragmentos no completados.
- RF-14: Cuando el fichero destino exista sin estado previo, el sistema deberá informar del error al usuario. 
- RF-15: Cuando todos los fragmentos sean válidos, el sistema deberá verificar el hash global, informar del éxito y eliminar el fichero de estado.
- RF-16: Si el servidor no soporta peticiones por rango, entonces el sistema deberá abortar con un error claro antes de escribir datos.
- RF-17: Si el tamaño del recurso remoto difiere del indicado en el manifest, entonces el sistema deberá abortar con un error claro.
- RF-18: Mientras dure la descarga, el sistema deberá mostrar un progreso textual simple (fragmentos completados/total y bytes).
- RF-19: Si no hay espacio suficiente para el fichero final, entonces el sistema deberá abortar antes de empezar a descargar.

## 5. Requisitos no funcionales
- RNF-1: Debe funcionar en Ubuntu jammy (Python 3.10) usando solo la biblioteca estándar (constitución §1).
- RNF-2: El consumo de memoria debe estar acotado e ser independiente del tamaño del fichero (ficheros >3 GB).
- RNF-3: Todos los mensajes al usuario son traducibles; código y comentarios en inglés (constitución §6).
- RNF-4: Códigos de salida: 0 en caso de éxito, distinto de 0 en cualquier error.
- RNF-5: El formato del manifest incluye versión para no romper compatibilidad futura.
- RNF-6: La lógica es independiente de la interfaz de línea de comandos (constitución §3).

## 6. Casos límite
- Fichero vacío o menor que un fragmento; último fragmento más corto.
- Redirecciones HTTP; recurso que cambia entre la generación del manifest y la descarga.
- Manifest corrupto, de versión desconocida o con hashes de longitud incorrecta.
- Disco lleno o destino sin permisos de escritura; directorio de estado inaccesible.
- Corte de red a mitad de fragmento; Ctrl-C del usuario (el estado debe quedar consistente).
- Fichero destino mayor que el esperado.
- Dos descargas simultáneas sobre el mismo destino.

## 7. Fuera de alcance
- Descargas en paralelo (el MVP es secuencial; no se prohíbe a futuro).
- Autenticación y proxies propios.
- Múltiples ficheros por manifest y mirrors.
- Firma criptográfica del manifest.
- Protocolos distintos de HTTP/HTTPS.

## 8. Criterios de finalización
- Se genera un manifest correcto desde fichero local o desde URL (RF-1..7).
- Una descarga completa produce un fichero idéntico al original y sin temporales (RF-8, RF-9, RF-15).
- Una descarga interrumpida se reanuda descargando solo lo pendiente (RF-12..14).
- Un fragmento corrupto provoca reintentos y, si persiste, aborto con error (RF-10).
- Todos los errores listados producen código de salida distinto de 0 y mensaje traducible.
- `pytest -q` pasa completo, sin red real.

## 9. Dudas abiertas
- [NECESITA ACLARACIÓN] Valores por defecto de tamaño de fragmento, número N de reintentos y algoritmo de hash.
- [NECESITA ACLARACIÓN] Ubicación por defecto del directorio de estado y cómo se identifica el estado de cada descarga (p. ej. por hash del manifest + destino).
- [NECESITA ACLARACIÓN] Si el hash global es obligatorio o puede omitirse en ficheros enormes (coste de lectura extra).
- [NECESITA ACLARACIÓN] Comportamiento exacto si el fichero destino existe y es de otro fichero (¿se sobrescribe, se pide confirmación?).
- [NECESITA ACLARACIÓN] Cómo obtiene el descargador la URL del fichero: ¿siempre explícita o puede venir en el manifest (RF-7)?
