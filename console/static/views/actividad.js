// Vista Actividad: el equipo hablando.
//
// No es un lector de conversaciones —el texto de los mensajes no se guarda en ninguna parte,
// a propósito— sino un mapa de quién habla con quién y cuándo. Cada mensaje enciende su
// arista y la deja apagarse: con un vistazo de dos segundos se ve si el equipo está
// trabajando en equipo o cada uno por su lado.
//
// Mecánica del brillo:
//   - Se sondea /api/events/pulse cada POLL_MS y cada evento nuevo entra en un buffer.
//   - La animación corre con el reloj del navegador (requestAnimationFrame), no al ritmo de
//     las respuestas: así un tirón de red no produce saltos, solo un relleno más tarde.
//   - La intensidad de una arista es la suma de exp(-Δt/TAU) de sus mensajes recientes, así
//     que un mensaje suelto la enciende y se apaga solo, y una ráfaga la mantiene viva.

const ROLE_COLORS = {
  manager: "#6ea8fe", backend: "#5ad19a", frontend: "#f7b955",
  devops: "#c78bf0", cypress: "#ff7a90", console: "#4dd0e1",
};
const colorFor = (name) => ROLE_COLORS[name] || "#8b93a7";

const POLL_MS = 2500;          // sondeo de eventos nuevos
const STATUS_MS = 5000;        // estado vivo de los agentes (pi-link)
const TAU_MS = 4000;           // constante de decaimiento del brillo
const GLOW_WINDOW_MS = 10000;  // más viejo que esto ya no ilumina nada
const TRAVEL_MS = 1400;        // lo que tarda el punto en recorrer la arista
const MAX_RECENT = 300;
const LIST_MAX = 60;

const WINDOWS = [
  { label: "1 min", ms: 60000 },
  { label: "1 h", ms: 3600000 },
  { label: "24 h", ms: 86400000 },
  { label: "7 d", ms: 604800000 },
];

const SVG_NS = "http://www.w3.org/2000/svg";
const W = 680, H = 420, R = 150, NODE_R = 42;
const PAIR_WINDOW_MS = 60000;  // tolerancia para casar un envío con su entrega

let root = null, pollTimer = null, statusTimer = null, frame = null;
let cursor = null;
let recent = [];           // {from, to, ts} de los últimos GLOW_WINDOW_MS
let edgeEls = new Map();   // "a→b" -> {path, glow, len}
let nodeEls = new Map();   // nombre -> {ring, circle}
let windowMs = 3600000;
let listItems = [];

const MARKUP = `
  <div class="view-head">
    <p class="meta" id="act-meta">Cargando…</p>
    <div class="controls">
      <div class="segmented" id="act-window"></div>
    </div>
  </div>
  <section class="grid graph-grid">
    <div class="panel">
      <h2>Interacción entre agentes <small id="act-sub"></small></h2>
      <div class="graph-wrap"><svg id="graph" viewBox="0 0 ${W} ${H}"></svg></div>
    </div>
    <div class="panel">
      <h2>Mensajes <small>· más recientes primero</small></h2>
      <ul class="events" id="act-list"></ul>
    </div>
  </section>
`;

export async function mount(container) {
  root = container;
  container.innerHTML = MARKUP;
  renderWindowPicker();

  await buildGraph();
  await loadList();
  await poll();
  await loadStatus();

  pollTimer = setInterval(() => { if (visible()) poll(); }, POLL_MS);
  statusTimer = setInterval(() => { if (visible()) loadStatus(); }, STATUS_MS);
  frame = requestAnimationFrame(animate);
}

export function unmount() {
  clearInterval(pollTimer); clearInterval(statusTimer); cancelAnimationFrame(frame);
  pollTimer = statusTimer = frame = null;
  root = null; recent = []; listItems = []; cursor = null;
  edgeEls.clear(); nodeEls.clear();
}

const visible = () => document.visibilityState === "visible";

function renderWindowPicker() {
  const box = root.querySelector("#act-window");
  box.innerHTML = WINDOWS.map((w) =>
    `<button data-ms="${w.ms}" class="${w.ms === windowMs ? "active" : ""}">${w.label}</button>`
  ).join("");
  box.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-ms]");
    if (!btn) return;
    windowMs = Number(btn.dataset.ms);
    box.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    buildGraph();
  });
}

// ── Grafo ───────────────────────────────────────────────────────────────────

async function buildGraph() {
  const [graph, system] = await Promise.all([
    fetch(`/api/events/graph?window_ms=${windowMs}`).then((r) => r.json()).catch(() => ({ edges: [] })),
    fetch("/api/system").then((r) => r.json()).catch(() => ({ containers: [] })),
  ]);
  if (!root) return;

  // Los nodos salen de los contenedores que existen y de quien aparezca en los eventos: así
  // se ve un agente aunque esté callado, y se ve la consola en cuanto habla (el cron).
  const names = new Set((system.containers || []).map((c) => c.role).filter((r) => r !== "console"));
  (graph.edges || []).forEach((e) => { names.add(e.from); names.add(e.to); });
  const nodes = [...names].filter(Boolean).sort();

  const svg = root.querySelector("#graph");
  svg.innerHTML = defs();
  edgeEls.clear(); nodeEls.clear();

  const positions = layout(nodes);
  (graph.edges || []).forEach((edge) => drawEdge(svg, positions, edge));
  nodes.forEach((name) => drawNode(svg, positions.get(name), name));

  const total = (graph.edges || []).reduce((a, e) => a + e.count, 0);
  root.querySelector("#act-sub").textContent =
    `· ${total} mensaje(s) en la ventana` + (graph.source === "received" ? " (vistos por quien los recibe)" : "");
  if (!total) {
    root.querySelector("#act-meta").textContent =
      "Todavía no hay mensajes registrados. En cuanto un agente use link_send, aparecerá aquí.";
  }
}

// Una punta de flecha por color de emisor: `marker` no hereda el `stroke` del trazo, así que
// no vale con uno solo si se quiere que la flecha vaya del color de quien habla.
function defs() {
  const markers = Object.entries(ROLE_COLORS).concat([["_otro", "#8b93a7"]]).map(([name, color]) =>
    // markerUnits="userSpaceOnUse" es lo que impide que la punta crezca con el grosor del
    // trazo: sin ello, una arista muy transitada dibuja un triángulo enorme.
    `<marker id="arrow-${name}" viewBox="0 0 10 10" refX="9" refY="5"
             markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
       <path d="M0 0 L10 5 L0 10 z" fill="${color}" /></marker>`
  ).join("");
  return `<defs>${markers}</defs>`;
}

const markerFor = (name) => `url(#arrow-${ROLE_COLORS[name] ? name : "_otro"})`;

function layout(nodes) {
  const positions = new Map();
  const cx = W / 2, cy = H / 2;
  nodes.forEach((name, i) => {
    const angle = (-Math.PI / 2) + (2 * Math.PI * i) / nodes.length;
    positions.set(name, { x: cx + R * Math.cos(angle), y: cy + R * Math.sin(angle) });
  });
  return positions;
}

function drawEdge(svg, positions, edge) {
  const a = positions.get(edge.from), b = positions.get(edge.to);
  if (!a || !b) return;
  const d = curve(a, b);

  // Dos trazos por arista: el fino permanente (volumen acumulado en la ventana) y el grueso
  // que se enciende con cada mensaje. Separarlos evita tener que recalcular el grosor base
  // en cada fotograma.
  const base = document.createElementNS(SVG_NS, "path");
  base.setAttribute("d", d);
  base.setAttribute("class", "edge-base");
  base.setAttribute("stroke-width", String(Math.min(6, 1 + Math.log2(edge.count + 1))));
  base.setAttribute("marker-end", markerFor(edge.from));
  svg.appendChild(base);

  const glow = document.createElementNS(SVG_NS, "path");
  glow.setAttribute("d", d);
  glow.setAttribute("class", "edge-glow");
  glow.setAttribute("stroke", colorFor(edge.from));
  glow.setAttribute("stroke-opacity", "0");
  svg.appendChild(glow);

  const tip = document.createElementNS(SVG_NS, "circle");
  tip.setAttribute("r", "4");
  tip.setAttribute("class", "edge-tip");
  tip.setAttribute("fill", colorFor(edge.from));
  tip.setAttribute("opacity", "0");
  svg.appendChild(tip);

  edgeEls.set(`${edge.from}→${edge.to}`, { glow, tip, path: base, count: edge.count });
}

// Curva desplazada hacia un lado: así A→B y B→A no se pisan y se ve que son dos flujos.
function curve(a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const off = 30;
  // Se recortan los extremos hasta el borde de cada nodo: así la línea no entra en el círculo
  // y la punta de flecha queda visible justo fuera del destino.
  const gap = NODE_R + 8;
  const from = { x: a.x + (dx / len) * gap, y: a.y + (dy / len) * gap };
  const to = { x: b.x - (dx / len) * gap, y: b.y - (dy / len) * gap };
  const mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2;
  return `M ${from.x} ${from.y} Q ${mx - (dy / len) * off} ${my + (dx / len) * off} ${to.x} ${to.y}`;
}

function drawNode(svg, pos, name) {
  if (!pos) return;
  const group = document.createElementNS(SVG_NS, "g");
  group.setAttribute("transform", `translate(${pos.x} ${pos.y})`);

  const ring = document.createElementNS(SVG_NS, "circle");
  ring.setAttribute("r", String(NODE_R + 5));
  ring.setAttribute("class", "node-ring");
  ring.setAttribute("stroke", colorFor(name));
  ring.setAttribute("stroke-opacity", "0");
  group.appendChild(ring);

  const circle = document.createElementNS(SVG_NS, "circle");
  circle.setAttribute("r", String(NODE_R));
  circle.setAttribute("class", "node");
  circle.setAttribute("stroke", colorFor(name));
  group.appendChild(circle);

  const label = document.createElementNS(SVG_NS, "text");
  label.setAttribute("class", "node-label");
  label.setAttribute("text-anchor", "middle");
  label.setAttribute("dy", "4");
  label.textContent = name;
  group.appendChild(label);

  const status = document.createElementNS(SVG_NS, "text");
  status.setAttribute("class", "node-status");
  status.setAttribute("text-anchor", "middle");
  status.setAttribute("dy", String(NODE_R + 18));
  group.appendChild(status);

  svg.appendChild(group);
  nodeEls.set(name, { ring, circle, status });
}

// ── Animación ───────────────────────────────────────────────────────────────

function animate() {
  frame = requestAnimationFrame(animate);
  if (!root) return;
  const now = Date.now();
  recent = recent.filter((e) => now - e.ts < GLOW_WINDOW_MS);

  const intensity = new Map();
  for (const event of recent) {
    const key = `${event.from}→${event.to}`;
    intensity.set(key, (intensity.get(key) || 0) + Math.exp(-(now - event.ts) / TAU_MS));
  }

  for (const [key, el] of edgeEls) {
    const value = Math.min(1, intensity.get(key) || 0);
    el.glow.setAttribute("stroke-opacity", value.toFixed(3));
    el.glow.setAttribute("stroke-width", (2 + value * 5).toFixed(2));

    // El punto viaja por la arista con el mensaje más reciente que siga en vuelo.
    const travelling = recent.filter((e) => `${e.from}→${e.to}` === key && now - e.ts < TRAVEL_MS);
    if (travelling.length) {
      const progress = (now - travelling[travelling.length - 1].ts) / TRAVEL_MS;
      const length = el.path.getTotalLength();
      const point = el.path.getPointAtLength(length * progress);
      el.tip.setAttribute("cx", point.x);
      el.tip.setAttribute("cy", point.y);
      el.tip.setAttribute("opacity", String(1 - progress));
    } else {
      el.tip.setAttribute("opacity", "0");
    }
  }

  // Un nodo brilla cuando acaba de hablar o de ser hablado.
  for (const [name, el] of nodeEls) {
    let value = 0;
    for (const event of recent) {
      if (event.from === name || event.to === name) {
        value += Math.exp(-(now - event.ts) / TAU_MS);
      }
    }
    el.ring.setAttribute("stroke-opacity", Math.min(0.9, value).toFixed(3));
  }
}

// ── Datos ───────────────────────────────────────────────────────────────────

async function poll() {
  try {
    const url = cursor ? `/api/events/pulse?since=${cursor}` : "/api/events/pulse";
    const data = await (await fetch(url)).json();
    if (!root) return;
    cursor = data.cursor;
    const fresh = (data.events || []).filter((e) => e.type.startsWith("link.message"));
    if (!fresh.length) return;

    let needsRebuild = false;
    for (const event of fresh) {
      const [from, to] = direction(event);
      if (!from || !to) continue;
      recent.push({ from, to, ts: Date.now() });   // reloj local: es lo que anima
      if (!edgeEls.has(`${from}→${to}`)) needsRebuild = true;
    }
    if (recent.length > MAX_RECENT) recent = recent.slice(-MAX_RECENT);

    prependToList(fresh);
    // Un par que todavía no tenía arista (primer mensaje entre esos dos): hay que redibujar
    // para que el brillo tenga por dónde correr.
    if (needsRebuild) buildGraph();
  } catch (_) { /* el siguiente sondeo lo recupera */ }
}

// `link.message.sent` va de agent a peer; `link.message.received`, al revés.
function direction(event) {
  return event.type.endsWith(".received")
    ? [event.peer, event.agent]
    : [event.agent, event.peer];
}

async function loadStatus() {
  try {
    const system = await (await fetch("/api/system")).json();
    if (!root) return;
    const terminals = (system.link || {}).terminals || {};
    for (const [name, el] of nodeEls) {
      const agent = terminals[name];
      el.status.textContent = agent ? (agent.status || "") : "";
      el.circle.classList.toggle("thinking", agent?.status === "thinking");
      el.circle.classList.toggle("offline", !agent);
    }
  } catch (_) { /* los nodos se quedan como estaban */ }
}

async function loadList() {
  try {
    const data = await (await fetch(`/api/events?type=link.message&limit=${LIST_MAX * 2}`)).json();
    if (!root) return;
    listItems = data.events || [];
    renderList();
  } catch (_) { /* la lista se rellenará con el sondeo */ }
}

function prependToList(events) {
  const known = new Set(listItems.map((e) => e.id));
  listItems = [...events.filter((e) => !known.has(e.id)).reverse(), ...listItems].slice(0, LIST_MAX * 2);
  renderList();
}

/**
 * Un mensaje deja dos rastros —el envío del emisor y la entrega del receptor— y en la lista
 * tiene que verse como una sola línea, no como dos mensajes distintos. Se casan por
 * (emisor, receptor) dentro de PAIR_WINDOW_MS, y la entrega aporta lo que el envío no sabe:
 * cuánto tardó en llegar (pi-link agrupa los entrantes y los retiene mientras compacta).
 *
 * Una entrega sin envío registrado no se descarta: significa que quien habló no tiene la
 * extensión cargada, y eso también hay que poder verlo.
 */
function mergeMessages(events) {
  const rows = [];
  const open = new Map(); // "a→b" -> fila esperando su entrega
  for (const event of [...events].sort((a, b) => a.ts - b.ts)) {
    const [from, to] = direction(event);
    if (!from || !to) continue;
    const key = `${from}→${to}`;
    if (event.type.endsWith(".sent")) {
      const row = {
        id: event.id, ts: event.ts, from, to,
        chars: event.payload?.chars ?? null,
        failed: event.payload?.ok === false,
        delivered_ms: null, orphan: false,
      };
      rows.push(row);
      open.set(key, row);
    } else {
      const pending = open.get(key);
      if (pending && event.ts - pending.ts >= 0 && event.ts - pending.ts <= PAIR_WINDOW_MS) {
        pending.delivered_ms = event.ts - pending.ts;
        open.delete(key);
      } else {
        rows.push({
          id: event.id, ts: event.ts, from, to,
          chars: event.payload?.chars ?? null,
          failed: false, delivered_ms: 0, orphan: true,
        });
      }
    }
  }
  return rows.reverse();
}

function renderList() {
  const list = root.querySelector("#act-list");
  const rows = mergeMessages(listItems).slice(0, LIST_MAX);
  if (!rows.length) {
    list.innerHTML = '<li class="meta">Sin mensajes registrados todavía.</li>';
    root.querySelector("#act-meta").textContent =
      "Sin mensajes todavía · se guarda quién y cuándo, nunca el texto";
    return;
  }
  list.innerHTML = rows.map((row) => {
    const time = new Date(row.ts).toLocaleTimeString("es-ES");
    const delivery = row.failed
      ? '<span class="tag bad">no entregado</span>'
      : row.delivered_ms != null
        ? `<span class="tag" title="${row.orphan ? "entrega sin envío registrado" : "tiempo hasta la entrega"}">✓${
            row.orphan ? "" : " " + (row.delivered_ms < 1000 ? row.delivered_ms + " ms" : (row.delivered_ms / 1000).toFixed(1) + " s")}</span>`
        : "";
    return `<li class="${row.failed ? "failed" : ""}">
      <span class="mono dim">${time}</span>
      <span class="dot" style="background:${colorFor(row.from)}"></span>${row.from}
      <span class="arrow">→</span>${row.to}
      <span class="dim">${row.chars ? row.chars + " car." : ""}</span>
      ${delivery}
    </li>`;
  }).join("");
  root.querySelector("#act-meta").textContent =
    `${rows.length} mensaje(s) recientes · se guarda quién y cuándo, nunca el texto`;
}
