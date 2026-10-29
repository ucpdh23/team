// Documentación compartida del repositorio (`./docs`, montada como /docs en los agentes).
// La consola y los agentes ven los mismos archivos; esta vista permite revisarlos y editarlos.
import * as browser from "./filebrowser.js";

export const mount = (container) => browser.mount(container, {
  base: "/api/docs",
  hash: "docs",
  scope: "docs",
  flat: true,
  rootLabel: () => "docs",
  missing: () => "No se encontró la carpeta compartida docs/.",
  editable: true,
});
export const unmount = browser.unmount;
