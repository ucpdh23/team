// Vista Skills: los skills (propios de cada agente y compartidos) y el AGENTS.md de cada uno,
// editables. Todo el trabajo lo hace filebrowser.js; la API es /api/skills (console/skills.py).
import * as browser from "./filebrowser.js";

export const mount = (container) => browser.mount(container, {
  base: "/api/skills",
  hash: "skills",
  rootLabel: (scope) => (scope === "shared" ? "compartidos" : scope),
  missing: (scope) => `${scope} no tiene nada que mostrar todavía.`,
  editable: true,
});
export const unmount = browser.unmount;
