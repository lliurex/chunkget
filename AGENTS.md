# AGENTS.md — chunkget

## Proyecto
Herramienta de linea de comandos que permite descargar ficheros principalmente de gran tamaño ( > 3GB ) de forma fragmentada para que en conexiones inestables se pueda garantizar la descarga exitosa del fichero. La descarga se realizara siempre sobre un fichero final evitando ficheros temporales que aumenten el consumo de espacio. Ademas cada una de esas descargas parciales validara mediante algun algoritmo de validacion que esta correcto, por lo cual debe existir una fuente de informacion que indique datos sobre ese fichero ( partes, algoritmo de validacion, etc ).

## Comandos
- Ejecutar: `chunkget <commando>`
- Tests: `pytest -q`

## Estilo y convenciones
- El orden de lectura ha de ser AGENTS.md, docs/constitution.md y posteriormente specs/NUMERO_SPEC/spec.md. Si se añadieran mas ficheros se indicarian en el spec.md. La spec define el mayor orden de preferencia.
- Existe un glosario en docs/glosary.md que define los terminos entre ingles y castellano.
- El proyecto sera codificado en python y se ejecutara sobre Linux. Ha de funcionar en la version de ubuntu jammy jellyfish (22.04), por lo que se ha de utilizar funcionalidades y librerias que esten empaquetadas en esta version de ubuntu. Tambien ha de funcionar en la version de ubuntu noble (24.04), por lo que si se usan librerias incompatibles tienes que avisar para tomar las medidas debidas.
- Para nombrar una release de ubuntu se utiliza la primera parte de su nombre: `jammy jellyfish` sera `jammy`, `noble numbat` sera `noble`

## Reglas
- Lee docs/constitution.md y la spec activa antes de tocar código.
- Nunca rompas compatibilidad entre versiones del servicio a no ser que se indique explicitamente. 
- No modifiques archivos dentro de `specs/` salvo peticion explicita. En su lugar propon que lo añada manualmente a ellos.
- Nunca ejecutes un comando de git que requiera escritura sin preguntar antes.

## Al terminar cualquier tarea de modificacion de codigo
- Ejecuta `pytest -q` y confirma en tu respuesta que todo pasa.
