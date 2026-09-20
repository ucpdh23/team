// Vista Sistema: qué hay levantado y qué está haciendo.
//
// Dos fuentes que se enseñan juntas pero se piden por separado (ver console/system.py):
// Docker dice lo que existe —incluido el agente parado, que es el que interesa ver— y el
// `GET /status` del hub de pi-link dice lo que está vivo: ocioso, pensando o ejecutando una
// herramienta, y cuánto contexto lleva gastado.
//
// La tabla se pinta en cuanto llega lo barato; la CPU/memoria y el disco, que tardan, entran
// después sin bloquear nada.

const ROLE_COLORS = {
  manager: "#6ea8fe", backend: "#5ad19a", frontend: "#f7b955",
  devops: "#c78bf0", cypress: "#ff7a90", console: "#4dd0e1",
};
const REFRESH_MS = 5000;

const STATUS_LABEL = {
  idle: "· ocioso", thinking: "✽ pensando", tool: "⚙ herramienta", compacting: "⇲ compactando",
};

let timer = null;
let root = null;

const bytes = (n) => {
  if (!n) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
};

const duration = (s) => {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
};

const MARKUP = `
  <div class="view-head">
    <p class="meta" id="sys-meta">Cargando…</p>
  </div>
  <section class="panel">
    <h2>Contenedores</h2>
    <div id="containers"></div>
  </section>
  <section class="grid">
    <div class="panel">
      <h2>Red <small id="net-sub"></small></h2>
      <div id="network"></div>
    </div>
    <div class="panel">
      <h2>Espacio <small>· todo el Docker de esta máquina</small></h2>
      <div id="disk">Calculando…</div>
    </div>
  </section>
`;

export async function mount(container) {
  root = container;
  container.innerHTML = MARKUP;
  await refresh();
  timer = setInterval(() => {
    // Sin esto, una pestaña olvidada en segundo plano seguiría interrogando al daemon de
    // Docker cada 5 segundos para siempre.
    if (document.visibilityState === "visible") refresh();
  }, REFRESH_MS);
  loadDisk();
}

export function unmount() {
  if (timer) clearInterval(timer);
  timer = null;
  root = null;
}

async function refresh() {
  let data, stats = {};
  try {
    data = await (await fetch("/api/system")).json();
  } catch (e) {
    root.querySelector("#sys-meta").textContent = "No se pudo consultar el sistema: " + e;
    return;
  }
  if (!root) return;

  renderContainers(data, stats);
  renderNetwork(data.network);
  renderMeta(data);

  // La CPU necesita dos muestras del daemon (~1 s), así que llega después y solo rellena.
  try {
    const res = await (await fetch("/api/system/stats")).json();
    if (root) renderContainers(data, res.stats || {});
  } catch (_) { /* la tabla ya está pintada sin CPU/memoria */ }
}

function renderMeta(data) {
  const up = data.containers.filter((c) => c.state === "running").length;
  const link = data.link || {};
  const linkText = link.available
    ? `malla pi-link: hub en ${link.hub}, ${Object.keys(link.terminals || {}).length} conectados`
    : `malla pi-link: sin datos (${link.reason || "desconocido"})`;
  root.querySelector("#sys-meta").textContent =
    `${up}/${data.containers.length} contenedores en marcha · ${linkText}` +
    (data.docker ? "" : " · sin acceso al socket de Docker");
}

function renderContainers(data, stats) {
  const terminals = (data.link || {}).terminals || {};
  const rows = data.containers.map((c) => {
    const agent = terminals[c.role];
    const color = ROLE_COLORS[c.role] || "#8b93a7";
    const running = c.state === "running";
    const stat = stats[c.name];
    const agentState = agent
      ? `<span class="pill ${agent.status || ""}">${STATUS_LABEL[agent.status] || agent.status || ""}` +
        (agent.since_s != null ? ` ${duration(agent.since_s)}` : "") + "</span>"
      : (running && c.role !== "console" ? '<span class="pill off">no conectado</span>' : "");
    const ctx = agent && agent.tokens != null && agent.context_window
      ? `${Math.round((agent.tokens / agent.context_window) * 100)}%`
      : "—";
    return `<tr class="${running ? "" : "down"}">
      <td><span class="dot" style="background:${color}"></span>${c.role}
          ${data.link && data.link.available && data.link.hub === c.role
             ? '<span class="tag">hub</span>' : ""}</td>
      <td>${running
        ? `<span class="state up">up</span> ${duration(c.uptime_s)}`
        : `<span class="state down">${c.state}</span> ${c.exit_code != null ? `(${c.exit_code})` : ""}`}</td>
      <td>${agentState}</td>
      <td class="num">${stat ? stat.cpu_percent.toFixed(1) + "%" : running ? "…" : "—"}</td>
      <td class="num">${stat ? bytes(stat.memory_bytes) : running ? "…" : "—"}</td>
      <td class="num">${ctx}</td>
      <td class="dim">${c.image}</td>
      <td class="dim">${c.ports.join(", ") || "—"}</td>
    </tr>`;
  });

  root.querySelector("#containers").innerHTML = data.containers.length
    ? `<table class="table">
         <thead><tr>
           <th>agente</th><th>contenedor</th><th>agente pi</th>
           <th class="num">cpu</th><th class="num">memoria</th><th class="num">contexto</th>
           <th>imagen</th><th>puertos</th>
         </tr></thead>
         <tbody>${rows.join("")}</tbody>
       </table>`
    : `<p class="meta">No se ve ningún contenedor del cluster. ¿Está levantado
       (<code>python setup.py --start</code>)?</p>`;
}

function renderNetwork(network) {
  const sub = root.querySelector("#net-sub");
  const box = root.querySelector("#network");
  if (!network || !network.available) {
    sub.textContent = "";
    box.innerHTML = '<p class="meta">Sin información de red.</p>';
    return;
  }
  sub.textContent = `· ${network.name}`;
  const team = network.members.filter((m) => m.team);
  const others = network.members.filter((m) => !m.team);
  const list = (items) => items.map((m) =>
    `<li><span class="mono">${m.ipv4 || "—"}</span> ${m.name}</li>`).join("");
  box.innerHTML =
    `<ul class="plain">${list(team)}</ul>` +
    (others.length
      // Lo que `devops` levanta (una BBDD de desarrollo, p. ej.) vive en esta red pero no es
      // del equipo: merece verse, y verse aparte.
      ? `<p class="meta sep">Contenedores ajenos al equipo en esta red (los levanta devops):</p>
         <ul class="plain">${list(others)}</ul>`
      : "");
}

async function loadDisk() {
  try {
    const disk = await (await fetch("/api/system/disk")).json();
    if (!root) return;
    const box = root.querySelector("#disk");
    if (!disk.available) { box.innerHTML = '<p class="meta">Sin datos de disco.</p>'; return; }
    const shortName = (name) =>
      // Los volúmenes anónimos son un sha256: enseñarlo entero ocupa dos líneas y no dice nada.
      /^[0-9a-f]{64}$/.test(name) ? `(anónimo ${name.slice(0, 10)}…)` : name;
    const volumes = disk.volumes.map((v) =>
      `<li class="${v.team ? "" : "dim"}"><span class="mono">${bytes(v.size)}</span> ` +
      `<span title="${v.name}">${shortName(v.name)}</span></li>`
    ).join("");
    box.innerHTML = `
      <ul class="plain">
        <li><span class="mono">${bytes(disk.images_size)}</span> imágenes
            <span class="dim">(${bytes(disk.images_reclaimable)} recuperables)</span></li>
        <li><span class="mono">${bytes(disk.volumes_size)}</span> volúmenes</li>
        <li><span class="mono">${bytes(disk.containers_size)}</span> capas de escritura</li>
      </ul>
      <p class="meta sep">Volúmenes más grandes:</p>
      <ul class="plain">${volumes}</ul>`;
  } catch (_) { /* el resto de la vista no depende de esto */ }
}
