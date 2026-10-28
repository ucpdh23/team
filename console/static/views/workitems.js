// Vista Workitems: /workspace/workitems de cada agente. Todo el trabajo lo hace filebrowser.js.
import * as browser from "./filebrowser.js";

export const mount = (container) => browser.mount(container, {
  base: "/api/workitems",
  hash: "workitems",
  rootLabel: (agent) => `${agent}/workitems`,
  missing: (agent) => `${agent} todavía no tiene <code>/workspace/workitems</code>. Al subir un fichero se crea.`,
  editable: false,
});
export const unmount = browser.unmount;
