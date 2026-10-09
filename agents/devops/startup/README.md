# Scripts de arranque

Cualquier `*.sh` que pongas aquí se ejecuta como root dentro del contenedor en **cada
arranque**, en orden alfabético, antes de iniciar Eclipse (si lo hay) y pi. Sirve para
lo que se pierde al recrear el contenedor: instalar un plugin de Eclipse (p. ej. Lombok),
otra versión de Java, paquetes del sistema, etc.

- Deben ser **idempotentes**: se reejecutan siempre (comprueba si ya está hecho antes de instalar).
- Un script que falla se avisa en los logs, pero el contenedor arranca igualmente.
- El directorio está montado en solo lectura; los scripts de esta carpeta no se versionan.
- Tras añadir o cambiar un script basta con reiniciar el contenedor
  (`docker restart <contenedor>`). La primera vez hay que recrearlo (`python setup.py --update <rol>`)
  para que el montaje exista.
