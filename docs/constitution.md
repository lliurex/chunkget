# Constitución de chunkget

1. **Stack mínimo.** Solo Python 3.10 (el de jammy) y su biblioteca estándar. Cualquier dependencia externa debe estar empaquetada en Ubuntu jammy (22.04) y justificarse en la spec.
2. **La spec manda.** No se escribe código sin una spec activa en `specs/`. Si código y spec divergen, se corrige primero la spec y después el código.
3. **Lógica separada de la interfaz.** El núcleo no importa `argparse`, no imprime ni lee `sys.argv`. La CLI solo parsea argumentos y presenta resultados.
4. **Tests obligatorios.** Todo cambio de comportamiento lleva su test, los tests no usan red real y `pytest -q` pasa completo antes de dar una tarea por terminada.
5. **Persistencia sin temporales.** Se escribe siempre sobre el fichero final, sin ficheros temporales. Cada fragmento se valida contra el manifiesto (partes, algoritmo, hashes) antes de darse por bueno, y la descarga puede reanudarse. Para la informacion extra se usara un fichero de estado.
6. **Inglés y gettext.** Código, comentarios y nombres en inglés. Todo mensaje al usuario pasa por gettext.
