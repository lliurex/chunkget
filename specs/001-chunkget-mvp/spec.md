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

## 4. Requisitos funcionales (EARS)
#### Requisitos compartidos
- RF1.1: El manifest cumplira los siguientes requisitos: ha de tener el nombre del fichero, la version del protocolo que esta usando de la aplicación, un campo url desde donde tendra que descargarse, el tamaño del fichero, el tamaño maximo del fragmento usado para la descarga, el hash global del fichero y un listado con todas los fragmentos que compone el fichero. Cada una de esos fragmentos constara de un identificador, el punto de inicio en el fichero, el punto de fin del fichero y el hash que confirma que ese fragmento es correcto.
- RF1.1.1: El manifest estara en un formato legible por una persona, elijiendo un json como opcion sino esta disponible YAML.
- RF1.2: El sistema tendra un valor por defecto para todas las opciones que no sean calculadas a partir del fichero de origen o de la url que se le indique. Para cualquiera de las funcionalidades de los usuarios del sistema, se usara el valor por defecto de las opciones, a no ser que el usuario indique otro valor.
- RF1.3: Si el usuario indica un valor nuevo para alguna opcion del sistema y este no esta soportado, el sistema terminara con un error distinto de 0 e indicara que el valor no es valido sugiriendo cuales puede utilizar.
- RF1.4: Los valores por defecto seran indicados en el plan.md, al igual que las rutas de ficheros en el sistema.

#### Comando de generación de manifest
- RF2: Cuando el publicador indique un fichero local como origen al ejecutar el comando `make-manifest`, el sistema debe generar un manifest calculando todos los datos a excepcion de la url, que se le solicitara al publicador como ultimo paso.
- RF3: Cuando el publicador indique un fichero en un servidor http/https como origen al ejecutar el comando `make-manifest`, el sistema le solicitara al publicador si quiere descargarse el fichero o si prefiere usar un fichero local como origen. En caso de que el publicador elija descargar el fichero se le preguntara la ruta donde se descargara. Una vez el fichero ya este en el sistema local se generara el fichero manifest igual que se genere en el RF2, con la excepcion de que el campo url se rellenara con la indicada como origen.
- RF4: Si el publicador indica un fichero como origen que no existe o una url que da error al ejecutar el comando `make-manifest`, el sistema notificara al usuario y saldra con un error distinto a 0.
- RF5: Si el manifest de salida ya existe, el sistema le consultara al publicador si desea sobreescribirlo. En caso afirmativo truncara el fichero y procedera como si este no existiera.

#### Comando de descarga
- RF6: Cuando el descargador indique como un manifest como una url al ejecutar el comando `download`, el sistema descargara el manifest en local como un fichero para posteriores usos.
- RF7: Cuando el descargador indique un maniest (ruta local o URL) al ejecutar el comando `download`, el sistema debera generar un fichero con el tamaño indicado por el manifest, y debera proceder la descarga de todas las partes indicadas en este ubicandolas en la parte correspondiente del fichero.
- RF8: Al iniciar la descarga del fichero mediante el comando `download` se debera generar un fichero de estado en una ruta que debera ser indicada en el plan.md en caso de que no exista ya. El fichero de estado contendra la ruta donde se esta descargando el fichero, una lista de las partes y en que estado se encuentra esa parte. Los diferentes estados de las partes estaran definidos en el plan.md.
- RF9: Al completar la descarga de un fragmento se procedera a validar contra un hash. Justo despues de comprobar la verificacion se cambiara el estado del fragmento en el fichero estado. En caso de que la comprobacion haya resultado en exito se marcara esa parte como correcta y pasara al siguiente fragmento. Si la comprobacion es erronea esa parte se marcara como fallida y pasara al siguiente fragmento.
- RF10: Al terminar de descargar todos los fragmentos, se trataran de descargar aquellos fragmentos que tengan estado fallido. Este proceso se repetira hasta un numero predefinido de 5 veces, que podra ser modificado por el descargador. En caso de que se superen el numero de intentos se notificara al usuario de que se han superado el numero de descargas fallidas.
- RF11: Si se descargan todas las partes de forma exitosa se procedera a hacer la validacion con el hash global. Si la validacion es exitosa se informara al usuario de que la descarga ha terminado. Si la validacion es erronea se informara al usuario de que ha habido un fallo en la validacion general.

## 5. Requisitos no funcionales
- RNF1: El sistema debe funcionar en Ubuntu jammy (python 3.10) prefiriendo usar librerias estandar pero se permitiran usar librerias que esten empaquetadas en el repositorio de ubuntu de la version correspondiente.
- RNF2: Todos los mensajes que de el sistema han de ser traducibles; El codigo y comentarios ha de estar en ingles.
- RNF3: Los codigos de salida seran 0 en caso de exito y distinto de 0 en caso de error. El listado de codigos se especificara en el plan.md
- RNF4: La logica sera independiente de la interfaz de linea de comandos, por lo que la interfaz solo importara librerias que implementen dicha logica.

## 6. Casos límite
- No hay suficiente espacio en el sistema para almacenar el fichero
- El manifest esta corrupto.
- Fichero vacio o menor que un fragmento.
- Corte de red a mitad fragmento; Ctrl-C del usuario.

## 7. Fuera de alcance
- Descargas en paralelo (el MVP es secuencial; no se prohíbe a futuro).
- Autenticación y proxies propios.
- Múltiples ficheros por manifest y mirrors.
- Firma criptográfica del manifest.
- Protocolos distintos de HTTP/HTTPS.

## 8. Criterios de finalizacion
- Se genera un manifest correcto desde fichero local o desde URL.
- Una descarga completa produce un fichero idéntico al original y sin temporales a excepcion de ficheros de estado.
- Una descarga interrumpida se reanuda descargando solo lo pendiente.
- Todos los errores listados producen código de salida distinto de 0 y mensaje traducible.

