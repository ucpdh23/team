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
