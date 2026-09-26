// Vista Tmux: las cinco sesiones a la vez, y una terminal real para la que elijas.
//
// Cada agente corre `pi` dentro de una sesión tmux; aquí se pide su contenido actual con
// `capture-pane` cada REFRESH_MS y se pinta tal cual, con sus colores. El mosaico es solo
// lectura a propósito: verlos a todos a la vez es barato, teclear en cinco a la vez no.
//
// Al ampliar un agente se ve igualmente en solo lectura, y el botón «Escribir» lo cambia por
// una terminal de verdad (terminal.js): lo tecleado llega al agente. Solo existe si la consola
// tiene CONSOLE_TOKEN (ver console/terminal.py); si no, el botón sale desactivado con el
// motivo. `docker exec -it <contenedor> tmux attach -t pi` (botón «attach») sigue ahí.
//
// El panel mide 220×50 caracteres, que no caben legibles en una celda de mosaico: se dibuja a
// tamaño real y se escala con CSS, de forma que se conserva la composición (bordes, columnas)
// aunque el texto quede diminuto. Para leer, se hace clic y se abre a tamaño completo.

import { openTerminal } from "/terminal.js";

const REFRESH_MS = 5000;
const LINES = 46;
const PANE_COLS = 220;

let root = null, timer = null, agents = [], expanded = null;
let interactive = { enabled: false, reason: "" };
let terminal = null;

const MARKUP = `
  <div class="view-head">
    <p class="meta" id="tmux-meta">Cargando…</p>
    <div class="controls">
      <button id="tmux-refresh" class="ghost" title="Actualizar ahora">↻</button>
    </div>
  </div>
  <section id="tmux-grid" class="tmux-grid"></section>
  <div id="tmux-modal" class="modal" hidden>
    <div class="modal-head">
      <strong id="tmux-modal-title"></strong>
      <span class="badge-live" id="tmux-modal-live" hidden>ESCRITURA ACTIVA</span>
      <span class="dim" id="tmux-modal-hint"></span>
      <button class="ghost small" id="tmux-modal-write">Escribir</button>
      <button class="ghost small" id="tmux-modal-close">Cerrar</button>
    </div>
    <pre class="tmux-pane full" id="tmux-modal-body"></pre>
    <div class="tmux-term" id="tmux-modal-term" hidden></div>
  </div>
`;

export async function mount(container) {
  root = container;
  container.innerHTML = MARKUP;
  container.querySelector("#tmux-refresh").addEventListener("click", refreshPanes);
  container.querySelector("#tmux-modal-close").addEventListener("click", closeModal);
  container.querySelector("#tmux-modal-write").addEventListener("click",
    () => (terminal ? leaveWrite() : enterWrite()));
  document.addEventListener("keydown", onKey);

  await loadAgents();
  await refreshPanes();
  // Cinco `exec` contra el daemon cada 5 s no son gratis: en cuanto la pestaña deja de verse,
  // se para.
  timer = setInterval(() => { if (document.visibilityState === "visible") refreshPanes(); },
                      REFRESH_MS);
}

export function unmount() {
  clearInterval(timer);
  document.removeEventListener("keydown", onKey);
  if (terminal) terminal.close();
  terminal = null; timer = null; root = null; agents = []; expanded = null;
}

function onKey(event) {
  // Con la terminal abierta, Esc es del agente (pi lo usa): solo se cierra con los botones.
  if (event.key === "Escape" && !terminal) closeModal();
}

async function loadAgents() {
  try {
    const data = await (await fetch("/api/tmux/panes")).json();
    agents = data.agents || [];
    interactive = data.interactive || { enabled: false, reason: "" };
  } catch (_) { agents = []; }
  if (!root) return;

  const up = agents.filter((a) => a.state === "running").length;
  root.querySelector("#tmux-meta").textContent = agents.length
    ? `${up}/${agents.length} agentes en marcha · mosaico en solo lectura, refresco cada ${REFRESH_MS / 1000} s · haz clic en uno para ampliarlo`
    : "No se ve ningún agente del equipo.";

  root.querySelector("#tmux-grid").innerHTML = agents.map((a) => `
    <div class="tmux-cell ${a.state === "running" ? "" : "down"}" data-agent="${a.agent}">
      <div class="tmux-cell-head">
        <strong>${a.agent}</strong>
        <span class="dim">${a.state === "running" ? a.container : a.status}</span>
        <button class="ghost small" data-copy="${a.container}"
                title="Copiar el comando para engancharte a esta sesión">attach</button>
      </div>
      <div class="tmux-scale"><pre class="tmux-pane" data-pane="${a.agent}"></pre></div>
    </div>`).join("");

  root.querySelector("#tmux-grid").onclick = onGridClick;
}

function onGridClick(event) {
  const container = event.target.dataset.copy;
  if (container) {
    const command = `docker exec -it ${container} tmux attach -t pi`;
    navigator.clipboard?.writeText(command).catch(() => {});
    event.target.textContent = "copiado";
    setTimeout(() => { event.target.textContent = "attach"; }, 1500);
    return;
  }
  const cell = event.target.closest(".tmux-cell");
  if (cell) openModal(cell.dataset.agent);
}

async function refreshPanes() {
  const running = agents.filter((a) => a.state === "running");
  await Promise.all(running.map(async (a) => {
    try {
      const data = await (await fetch(`/api/tmux/panes/${a.agent}?lines=${LINES}`)).json();
      if (!root) return;
      const pane = root.querySelector(`[data-pane="${a.agent}"]`);
      if (!pane) return;
      pane.innerHTML = data.error
        ? `<span class="dim">${escapeHtml(data.error)}</span>`
        : ansiToHtml(data.text || "");
      fitScale(pane);
      if (expanded === a.agent && !terminal) renderModal(a, data);
    } catch (_) { /* el siguiente refresco lo reintenta */ }
  }));
  for (const a of agents.filter((x) => x.state !== "running")) {
    const pane = root?.querySelector(`[data-pane="${a.agent}"]`);
    if (pane && !pane.innerHTML) {
      pane.innerHTML = `<span class="dim">contenedor ${a.state}</span>`;
    }
  }
}

/** Escala el panel para que sus 220 columnas quepan en el ancho de la celda. */
function fitScale(pane) {
  const box = pane.parentElement;
  if (!box || !box.clientWidth) return;
  const charWidth = measureChar(pane);
  const natural = PANE_COLS * charWidth;
  const scale = Math.min(1, box.clientWidth / natural);
  pane.style.transform = `scale(${scale.toFixed(3)})`;
  // La caja se queda con la altura real del contenido escalado, para que la celda no deje un
  // hueco enorme debajo.
  box.style.height = `${pane.scrollHeight * scale}px`;
}

let cachedCharWidth = 0;
function measureChar(pane) {
  if (cachedCharWidth) return cachedCharWidth;
  const ruler = document.createElement("span");
  ruler.textContent = "0".repeat(100);
  ruler.style.cssText = "position:absolute;visibility:hidden;white-space:pre";
  ruler.style.font = getComputedStyle(pane).font;
  document.body.appendChild(ruler);
  cachedCharWidth = ruler.getBoundingClientRect().width / 100;
  ruler.remove();
  return cachedCharWidth || 7;
}

function openModal(agent) {
  const info = agents.find((a) => a.agent === agent);
  if (!info || info.state !== "running") return;
  expanded = agent;
  const modal = root.querySelector("#tmux-modal");
  modal.hidden = false;
  root.querySelector("#tmux-modal-title").textContent = `${agent} · ${info.container}`;
  showReadOnly();
  refreshPanes();
}

// ── Modo escritura ──────────────────────────────────────────────────────────

const setHint = (text) => { root.querySelector("#tmux-modal-hint").textContent = text; };

/** El modal en su estado normal: la foto de `capture-pane`, sin teclado. */
function showReadOnly(note) {
  const write = root.querySelector("#tmux-modal-write");
  root.querySelector("#tmux-modal").classList.remove("writing");
  root.querySelector("#tmux-modal-live").hidden = true;
  root.querySelector("#tmux-modal-term").hidden = true;
  root.querySelector("#tmux-modal-body").hidden = false;
  write.textContent = "Escribir";
  write.disabled = !interactive.enabled;
  setHint(note || (interactive.enabled
    ? "solo lectura · Esc para cerrar · «Escribir» abre una terminal real"
    : `solo lectura · Esc para cerrar · ${interactive.reason}`));
}

function enterWrite() {
  if (terminal || !expanded || !interactive.enabled) return;
  const host = root.querySelector("#tmux-modal-term");
  root.querySelector("#tmux-modal-body").hidden = true;
  host.hidden = false;
  terminal = openTerminal(host, expanded, onTerminalState);
}

function leaveWrite(note) {
  if (terminal) terminal.close();
  terminal = null;
  if (!root) return;
  showReadOnly(note);
  refreshPanes();
}

function onTerminalState(state, detail) {
  if (!root) return;
  const write = root.querySelector("#tmux-modal-write");
  if (state === "connecting") {
    write.disabled = true;
    setHint("conectando…");
  } else if (state === "live") {
    root.querySelector("#tmux-modal").classList.add("writing");
    root.querySelector("#tmux-modal-live").hidden = false;
    write.textContent = "Solo lectura";
    write.disabled = false;
    setHint("Esc y Ctrl+C van al agente (Ctrl+C copia si hay selección) · Shift+arrastrar (Opción en Mac) para seleccionar");
  } else {
    // "error" o "closed": la terminal ya se ha desmontado sola; se vuelve a la vista normal.
    terminal = null;
    leaveWrite(detail ? `terminal cerrada: ${detail}` : "terminal cerrada");
  }
}

function renderModal(agent, data) {
  root.querySelector("#tmux-modal-body").innerHTML = data.error
    ? escapeHtml(data.error) : ansiToHtml(data.text || "");
}

function closeModal() {
  if (terminal) leaveWrite();
  expanded = null;
  const modal = root?.querySelector("#tmux-modal");
  if (modal) modal.hidden = true;
}

// ── ANSI → HTML ─────────────────────────────────────────────────────────────
//
// pi dibuja su interfaz con color, y en gris se pierde la mitad de la información (qué está
// pensando, qué es un error, qué es el prompt). Se traducen los códigos SGR que usa de verdad:
// reset, negrita/tenue, los 16 colores básicos, la paleta de 256 y color verdadero.

const BASE_COLORS = [
  "#1e222d", "#ff7a90", "#5ad19a", "#f7b955", "#6ea8fe", "#c78bf0", "#4dd0e1", "#c8cdd8",
  "#5a6070", "#ff9db0", "#7de0b4", "#ffd07a", "#93c0ff", "#dcaef5", "#7fe3ef", "#e6e8ee",
];

function xterm256(n) {
  if (n < 16) return BASE_COLORS[n];
  if (n < 232) {
    const i = n - 16;
    const level = (v) => (v === 0 ? 0 : 55 + v * 40);
    return `rgb(${level(Math.floor(i / 36))},${level(Math.floor(i / 6) % 6)},${level(i % 6)})`;
  }
  const grey = 8 + (n - 232) * 10;
  return `rgb(${grey},${grey},${grey})`;
}

const escapeHtml = (text) => text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function ansiToHtml(text) {
  let out = "";
  let open = false;
  let style = { fg: null, bg: null, bold: false, dim: false };
  const flush = () => {
    if (open) { out += "</span>"; open = false; }
    const css = [
      style.fg ? `color:${style.fg}` : "",
      style.bg ? `background:${style.bg}` : "",
      style.bold ? "font-weight:600" : "",
      style.dim ? "opacity:.65" : "",
    ].filter(Boolean).join(";");
    if (css) { out += `<span style="${css}">`; open = true; }
  };

  // eslint-disable-next-line no-control-regex
  const pattern = /\x1b\[([0-9;]*)m|\x1b\[[0-9;?]*[A-Za-z]/g;
  let last = 0, match;
  while ((match = pattern.exec(text)) !== null) {
    out += escapeHtml(text.slice(last, match.index));
    last = pattern.lastIndex;
    if (match[1] === undefined) continue;   // secuencia que no es de color: se descarta
    const codes = (match[1] || "0").split(";").map((n) => parseInt(n || "0", 10));
    for (let i = 0; i < codes.length; i++) {
      const code = codes[i];
      if (code === 0) style = { fg: null, bg: null, bold: false, dim: false };
      else if (code === 1) style.bold = true;
      else if (code === 2) style.dim = true;
      else if (code === 22) { style.bold = false; style.dim = false; }
      else if (code === 39) style.fg = null;
      else if (code === 49) style.bg = null;
      else if (code >= 30 && code <= 37) style.fg = BASE_COLORS[code - 30];
      else if (code >= 90 && code <= 97) style.fg = BASE_COLORS[code - 90 + 8];
      else if (code >= 40 && code <= 47) style.bg = BASE_COLORS[code - 40];
      else if (code >= 100 && code <= 107) style.bg = BASE_COLORS[code - 100 + 8];
      else if (code === 38 || code === 48) {
        const target = code === 38 ? "fg" : "bg";
        if (codes[i + 1] === 5) { style[target] = xterm256(codes[i + 2]); i += 2; }
        else if (codes[i + 1] === 2) {
          style[target] = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
          i += 4;
        }
      }
    }
    flush();
  }
  out += escapeHtml(text.slice(last));
  if (open) out += "</span>";
  return out;
}
