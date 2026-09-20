"""Consola del equipo team-pi.

Sexto contenedor del compose (servicio `console`, puerto 4070): observa al equipo y programa
tareas, sin participar en la malla pi-link ni ejecutar ningún agente. Hoy muestra el consumo
de los agentes agregando los ficheros de `pi-cost-counter` que cada rol deja en
`cost-tracking/<rol>/<AAAA>/<MM>/<DD>.jsonl`.

Solo librería estándar en el lado Python; las gráficas se dibujan en el navegador con Chart.js.

- Dentro del contenedor:  `python -m console`  (configuración por entorno, ver config.py)
- En el host, sin Docker: `python setup.py --console-local [PUERTO]`
"""
