# Prueba de interfaz de la consola

Comprueba la consola **en el navegador**, contra el contenedor levantado: que las tres vistas
pintan lo que deben y que ninguna lanza un error de JavaScript (Cypress falla el test ante
cualquier excepción no capturada de la página).

No añade ninguna dependencia al proyecto: reutiliza la imagen del agente `cypress`, que ya
trae Cypress y su navegador.

```bash
docker compose up -d console          # la consola tiene que estar levantada
docker run --rm --network "${CONTAINER_PREFIX:-pi}-net" \
  -v "$PWD/console/tests:/e2e" -w /e2e \
  --entrypoint cypress team-pi-cypress run --browser electron
```

La prueba **se siembra y se limpia sola**: crea sus propios eventos con agentes `demo-*`, los
borra al terminar (`DELETE /api/events?agent=…`) y no cuenta los mensajes reales del equipo
que haya en la base. Puede ejecutarse con el equipo trabajando sin ensuciarle el histórico.

Las capturas quedan en `cypress/screenshots/` (ignoradas por git).

## La terminal de la pestaña Tmux

`terminal.cy.js` comprueba que «Escribir» abre la terminal, que se distingue como modo
escritura y que se vuelve a solo lectura. **No teclea nada**, a propósito: contra un equipo real
lo tecleado llegaría a un `pi` de verdad. Sin `CONSOLE_TOKEN` en la consola lo que comprueba es
que el botón esté desactivado y diga por qué; para probar la terminal en sí hay que pasarle el
token de la consola:

```bash
docker run --rm --network "${CONTAINER_PREFIX:-pi}-net" \
  -v "$PWD/console/tests:/e2e" -w /e2e --entrypoint cypress team-pi-cypress \
  run --browser electron --env CONSOLE_TOKEN=<token de la consola> --spec cypress/e2e/terminal.cy.js
```

Que las teclas llegan al agente, que `Esc` no cierra el modal y que al cerrar no queda ningún
cliente enganchado en tmux (`tmux list-clients` vacío) solo se ha comprobado contra un agente
desechable, no está en esta suite.
