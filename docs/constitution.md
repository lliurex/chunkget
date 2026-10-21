# Constitución de chunkget

1. **Metodologia Spec-Driven Development** Se sigue la metodologia Spec-Driven Development. Cada funcionalidad se definira en specs/XXX-FUNCIONALIDAD/, que sera un directorio y contendra un fichero spec.md y un plan.md. spec.md contendra la deficion de la funcionalidad sin entrar en detalles tecnicos. Plan se encargara de detallar como se realiza la implementacion. 
2. **Stack.** Las herramientas se ejecutaran sobre la distribucion ubuntu jammy (22.04), por lo que el software usado debe estar disponible en los repositorios oficiales de este.
3. **Necesidad de spec.md y plan.md** No se escribe código sin tener spec.md y plan.md en `specs/`. Si el codigo diverge de lo que diga la spec y el plan , se corrige primero la spec, luego el plan y finalmente el código.
4. **Tests obligatorios.** Todo cambio de codigo comportamiento lleva su test, los tests no usan red externa, solo red local y `pytest -q` pasa completo antes de dar una tarea por terminada. 
5. **Persistencia sin temporales.** Se escribe siempre sobre el fichero final sin tener otros ficheros con copia del contenido.
6. **Idiomas** Código, comentarios, mensajes al usuario y definiciones el el codigo en inglés. Los mensajes que reciba los usuarios deberan ser traducibles mediante gettext.
7. **Control de versiones**. Todo el codigo se mantiene sobre git.
8. **Estructura de control de versiones**. La ultima version del proyecto se mantiene sobre la rama master. Si existe alguna limitación para que la ultima versión del codigo funcione sobre una release de ubuntu determinada se creara una rama con el nombre de la release. El codigo con el empaquetado estricto de debian estara en la rama debian/NOMBRE_RELEASE
