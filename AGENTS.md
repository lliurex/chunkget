# AGENTS.md — chunkget

## Proyecto
Herramienta de linea de comandos que permite descargar ficheros principalmente de gran tamaño ( > 3Gb ) de forma fragmentada para que en conexiones inestables se pueda garantizar la descarga exitosa del fichero. La descarga se realizara siempre sobre un fichero final evitando ficheros temporales que aumenten el consumo de espacio. Ademas cada una de esas descargas parciales validara mediante algun algoritmo de validacion que esta correcto, por lo cual debe existir una fuente de informacion que indique datos sobre ese fichero ( partes, algoritmo de validacion, etc ).

## Comandos
- Ejecutar: `chunkget <commando>`
- Tests: `pytest -q`

## Estilo y convenciones
- El proyecto sera codificado en python y se ejecutara principalmente sobre ubuntu. Ha de funcionar en la version de ubuntu jammy jellyfish (22.04), por lo que se ha de utilizar funcionalidades y librerias que esten empaquetadas en esta version de ubuntu
- El codigo ha de ser codificado en ingles, por lo que tanto los comentarios como todas las definiciones de nombres han de estan en dicho idioma.
- Los mensajes al usuario han de ser traducibles. Para ello se usara gettext
- Prioriza el uso de librerias estandar de python.
- El proyecto se mantiene en el control de versiones git.
- Para nombrar una release de ubuntu se utiliza la primera parte de su nombre: `jammy jellyfish` sera `jammy`, `noble numbat` sera `noble`
- El codigo se mantiene en la rama master de git. Si hay que hacer algun parche para que funcione para alguna release especifica de ubuntu se creara una rama de git con el nombre de la release especifico usando la convencion antes nombrada.
- Existira una carpeta llamada `debian` con todos los ficheros necesarios para empaquetado en las ramas de git `debian/NOMBRE_RELEASE` donde NOMBRE_RELEASE sera remplazado por el nombre de la release.

## Reglas
- Lee docs/constitution.md y la spec activa antes de tocar código.
- Nunca rompas compatibilidad entre versiones a no ser que se indique explicitamente.
- No modifiques archivos dentro de `specs/` salvo peticion explicita.
- Nunca ejecutes un comando de git sin preguntar antes.

## Al terminar cualquier tarea
- Ejecuta `pytest -q` y confirma en tu respuesta que todo pasa.
