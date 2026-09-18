"""Consola web de consumo de los agentes de team-pi.

Dashboard ligero (solo librería estándar en el lado Python; las gráficas se dibujan en el
navegador con Chart.js) que agrega los ficheros de `pi-cost-counter` que cada rol deja en
`cost-tracking/<rol>/<AAAA>/<MM>/<DD>.jsonl` y los muestra por agente y en el tiempo.

Se lanza desde `setup.py --console [PUERTO]`.
"""
