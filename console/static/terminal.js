// Terminal interactiva de un agente: xterm.js en el navegador, WebSocket hasta la consola, y de
// ahí un `tmux attach` dentro del contenedor (ver console/terminal.py).
//
// El servidor manda el tamaño de la ventana de tmux y el navegador se adapta a él, no al
// revés: las 220 columnas de pi no caben a un tamaño de letra cómodo en cualquier pantalla,
// así que se reduce la letra hasta que quepan (con un mínimo, y con scroll si aun así no).
//
// xterm.js viene de la CDN, como Chart.js, y se pide solo al abrir la primera terminal. Va con
// hash de integridad: una terminal es escritura en un agente, y un script alterado en esa
// página tendría acceso a ella.

const XTERM = "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0";
const XTERM_JS_SHA384 = "sha384-M169f14mRZOXm3hD/v2Ti0ThIT/RnAQagXA9nlE15yHAtrW19gdePJh/HaTzUOe/";
const XTERM_CSS_SHA384 = "sha384-8Xk9wy/gzEDUKrXtrmCFa2bBuK3BpjpDuL/p0SeKQX19Khl/M+lHOgD/CyYf7efP";

const FONT = 'ui-monospace, SFMono-Regular, Menlo, Consolas, "DejaVu Sans Mono", monospace';
// Ancho de un carácter monoespaciado como fracción de su tamaño de letra. Es una estimación
// para el primer ajuste; el segundo lo corrige con la medida real.
const CHAR_RATIO = 0.6;
const MIN_FONT = 8;
const MAX_FONT = 15;

// Los mismos colores que el mosaico (tmux.js), para que al pasar de uno a otro no cambie la
// paleta de pi.
const THEME = {
  background: "#0b0d13", foreground: "#c8cdd8", cursor: "#c8cdd8", selectionBackground: "#3a4256",
  black: "#1e222d", red: "#ff7a90", green: "#5ad19a", yellow: "#f7b955", blue: "#6ea8fe",
  magenta: "#c78bf0", cyan: "#4dd0e1", white: "#c8cdd8",
  brightBlack: "#5a6070", brightRed: "#ff9db0", brightGreen: "#7de0b4", brightYellow: "#ffd07a",
  brightBlue: "#93c0ff", brightMagenta: "#dcaef5", brightCyan: "#7fe3ef", brightWhite: "#e6e8ee",
};

let loading = null;

function loadXterm() {
  if (window.Terminal) return Promise.resolve();
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = `${XTERM}/css/xterm.css`;
    css.integrity = XTERM_CSS_SHA384;
    css.crossOrigin = "anonymous";
    document.head.appendChild(css);

    const script = document.createElement("script");
    script.src = `${XTERM}/lib/xterm.js`;
    script.integrity = XTERM_JS_SHA384;
    script.crossOrigin = "anonymous";
    script.onload = () => resolve();
    script.onerror = () => {
      loading = null;
      script.remove();
      css.remove();
      reject(new Error("no se pudo cargar xterm.js (¿el navegador tiene red?)"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

/**
 * Abre la terminal de `agent` dentro de `host`.
 *
 * `onState(estado, detalle)` recibe: "connecting", "live", "error" (con el motivo) y "closed"
 * (con el motivo si lo hay). Devuelve `{ close() }`; llamarlo desmonta la terminal y cierra
 * la conexión, y no dispara `onState`.
 */
export function openTerminal(host, agent, onState) {
  let ws = null, term = null, done = false, onResize = null;

  const finish = (state, detail) => {
    if (done) return;
    done = true;
    cleanup();
    onState(state, detail);
  };

  function cleanup() {
    if (onResize) window.removeEventListener("resize", onResize);
    onResize = null;
    if (ws) { ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null; try { ws.close(); } catch (_) {} }
    ws = null;
    if (term) { try { term.dispose(); } catch (_) {} }
    term = null;
    host.replaceChildren();
  }

  onState("connecting");
  loadXterm().then(() => {
    if (done) return;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${scheme}://${location.host}/api/tmux/attach/${encodeURIComponent(agent)}`);
    ws.binaryType = "arraybuffer";
    let opened = false, failure = null;

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        const message = JSON.parse(event.data);
        if (message.type === "ready") start(message.cols, message.rows);
        else if (message.type === "error") failure = message.message;
        else if (message.type === "ended") failure = "la sesión de tmux terminó";
        return;
      }
      if (term) term.write(new Uint8Array(event.data));
    };
    ws.onclose = () => finish(opened ? "closed" : "error",
      failure || (opened ? "" : "no se pudo abrir la terminal (¿falta el token, o el contenedor no responde?)"));
    ws.onerror = () => {};   // el detalle llega por onclose; el navegador no da más

    function start(cols, rows) {
      term = new window.Terminal({
        cols, rows, fontFamily: FONT, fontSize: MAX_FONT, theme: THEME,
        cursorBlink: true,
        // Con el ratón de tmux activo, xterm.js solo deja seleccionar manteniendo Shift (Opción
        // en Mac, si se activa esto).
        macOptionClickForcesSelection: true,
        // El historial lo lleva tmux (rueda del ratón = modo copia), no el navegador.
        scrollback: 0,
      });
      // Al engancharse, tmux pregunta qué terminal hay (DA1, DA2, DA3) y xterm.js contesta solo.
      // Esa respuesta llega cuando tmux ya no la espera y la reenvía como texto al programa del
      // panel: en pi acaba escrita en su caja de entrada ("[>0;276;0c"). tmux no la necesita,
      // porque TERM y el terminal-overrides de las imágenes ya le dicen lo que hace falta. Al
      // devolver true el parser da la consulta por atendida y no responde nada.
      for (const prefix of ["", ">", "="]) {
        term.parser.registerCsiHandler({ prefix, final: "c" }, () => true);
      }
      term.open(host);
      fit(cols);
      onResize = () => fit(cols);
      window.addEventListener("resize", onResize);

      // Con selección, Ctrl/Cmd+C copia; sin ella, sigue siendo la interrupción de siempre. Al
      // copiar se quita la selección, como en Windows Terminal: si no, el siguiente Ctrl+C
      // volvería a copiar y no habría forma de interrumpir al agente.
      term.attachCustomKeyEventHandler((e) => {
        if (e.type === "keydown" && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey
            && e.key.toLowerCase() === "c" && term.hasSelection()) {
          navigator.clipboard?.writeText(term.getSelection()).catch(() => {});
          term.clearSelection();
          return false;
        }
        return true;
      });

      term.onData((data) => { if (ws?.readyState === WebSocket.OPEN) ws.send(data); });
      term.onBinary((data) => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(Uint8Array.from(data, (c) => c.charCodeAt(0)));
      });
      opened = true;
      term.focus();
      onState("live");
    }
  }).catch((error) => finish("error", error.message));

  /** Ajusta la letra para que las `cols` columnas quepan en el ancho disponible. */
  function fit(cols) {
    if (!term) return;
    const available = host.clientWidth;
    if (!available) return;
    let size = Math.max(MIN_FONT, Math.min(MAX_FONT, Math.floor(available / (cols * CHAR_RATIO))));
    term.options.fontSize = size;
    // Segundo paso con la medida real: la estimación falla con tipografías más anchas.
    const screen = host.querySelector(".xterm-screen");
    const width = screen ? screen.getBoundingClientRect().width : 0;
    if (width > available && size > MIN_FONT) {
      size = Math.max(MIN_FONT, Math.floor(size * available / width));
      term.options.fontSize = size;
    }
  }

  return {
    close() {
      if (done) return;
      done = true;
      cleanup();
    },
  };
}
