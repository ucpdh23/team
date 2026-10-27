// Vista Workitems: navegar /workspace/workitems de cada agente, leer sus documentos y subir
// ficheros. Es la cara web de /api/workitems (console/workitems.py): lo que se ve aquí se
// puede hacer igual con curl, y el botón «curl» de cada vista da la orden exacta.

const PREVIEW_MAX = 512 * 1024;
const TEXTLIKE = /\.(md|markdown|txt|log|json|ya?ml|toml|ini|csv|xml|html?|css|svg|js|ts|tsx|py|java|kt|sh|sql|feature|properties|gradle|env)$/i;

let root = null, agents = [], state = { agent: null, path: "" };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const enc = (path) => path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
const apiUrl = (agent, path) => `/api/workitems/${agent}${path ? "/" + enc(path) : ""}`;
const size = (n) => n == null ? "" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
const when = (ts) => new Date(ts).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });

const MARKUP = `
  <div class="view-head">
    <p class="meta" id="wi-meta">Cargando…</p>
    <div class="controls">
      <button id="wi-curl" class="ghost small" title="Copia el curl equivalente a lo que estás viendo">curl</button>
      <button id="wi-upload" class="ghost">⬆ Subir</button>
      <input type="file" id="wi-file" multiple hidden />
    </div>
  </div>
  <section class="panel">
    <div id="wi-agents" class="segmented"></div>
    <p id="wi-crumbs" class="meta"></p>
    <div id="wi-list"></div>
  </section>
  <section class="panel" id="wi-preview" hidden></section>
`;

export async function mount(container) {
  root = container;
  container.innerHTML = MARKUP;
  const q = new URLSearchParams((location.hash.split("?")[1]) || "");
  state = { agent: q.get("agent"), path: q.get("path") || "" };
  container.querySelector("#wi-upload").addEventListener("click", () => container.querySelector("#wi-file").click());
  container.querySelector("#wi-file").addEventListener("change", (e) => upload([...e.target.files]));
  container.querySelector("#wi-curl").addEventListener("click", copyCurl);
  // Arrastrar ficheros sobre la lista los sube a la carpeta actual.
  const dropZone = container.querySelector("#wi-list");
  dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragging"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault(); dropZone.classList.remove("dragging");
    upload([...e.dataTransfer.files]);
  });
  await loadAgents();
}

export function unmount() { root = null; agents = []; }

async function getJson(url, options) {
  const r = await fetch(url, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

async function loadAgents() {
  agents = (await getJson("/api/workitems")).agents;
  if (!root) return;
  if (!state.agent || !agents.some((a) => a.agent === state.agent)) {
    state = { agent: (agents.find((a) => a.exists) || agents[0]).agent, path: "" };
  }
  const bar = root.querySelector("#wi-agents");
  bar.innerHTML = agents.map((a) =>
    `<button data-agent="${a.agent}" class="${a.agent === state.agent ? "active" : ""}" ${a.exists ? "" : 'title="sin carpeta workitems"'}>${a.agent}${a.exists ? ` · ${a.items}` : ""}</button>`).join("");
  bar.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => go(b.dataset.agent, "")));
  await go(state.agent, state.path);
}

function setHash() {
  const q = new URLSearchParams({ agent: state.agent });
  if (state.path) q.set("path", state.path);
  history.replaceState(null, "", `#/workitems?${q}`);
}

async function go(agent, path) {
  if (!root) return;
  state = { agent, path };
  setHash();
  root.querySelectorAll("#wi-agents button").forEach((b) => b.classList.toggle("active", b.dataset.agent === agent));
  root.querySelector("#wi-preview").hidden = true;
  const list = root.querySelector("#wi-list");
  const info = agents.find((a) => a.agent === agent);
  renderCrumbs();
  if (info && !info.exists) {
    list.innerHTML = `<p class="meta">${agent} todavía no tiene <code>/workspace/workitems</code>. Al subir un fichero se crea.</p>`;
    root.querySelector("#wi-meta").textContent = "";
    return;
  }
  try {
    const data = await getJson(apiUrl(agent, path));
    if (!root || state.agent !== agent || state.path !== path) return;
    if (!data.entries) {   // la ruta era un fichero (enlace directo): se abre su carpeta
      return go(agent, path.split("/").slice(0, -1).join("/"));
    }
    renderList(data);
  } catch (e) {
    // Si la ruta es un fichero la API devuelve su contenido, no JSON: se previsualiza.
    list.innerHTML = `<p class="meta error">${esc(e.message)}</p>`;
  }
}

function renderCrumbs() {
  const parts = state.path.split("/").filter(Boolean);
  let acc = "";
  const links = [`<a href="#" data-path="">${state.agent}/workitems</a>`].concat(parts.map((p) => {
    acc += (acc ? "/" : "") + p;
    return `<a href="#" data-path="${esc(acc)}">${esc(p)}</a>`;
  }));
  const el = root.querySelector("#wi-crumbs");
  el.innerHTML = links.join(" / ");
  el.querySelectorAll("a").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault(); go(state.agent, a.dataset.path);
  }));
}

function renderList(data) {
  const list = root.querySelector("#wi-list");
  const dirs = data.entries.filter((e) => e.type === "dir").length;
  root.querySelector("#wi-meta").textContent =
    `${dirs} carpeta(s), ${data.entries.length - dirs} fichero(s) · arrastra ficheros aquí para subirlos`;
  if (!data.entries.length) {
    list.innerHTML = '<p class="meta">Carpeta vacía.</p>';
    return;
  }
  list.innerHTML = `<table class="table"><thead><tr><th>Nombre</th><th class="num">Tamaño</th><th>Modificado</th><th></th></tr></thead><tbody>${
    data.entries.map((e) => `<tr data-path="${esc(e.path)}" data-type="${e.type}" style="cursor:pointer">
      <td>${e.type === "dir" ? "📁" : "📄"} ${esc(e.name)}</td>
      <td class="num dim">${size(e.size)}</td><td class="dim">${when(e.modified)}</td>
      <td>${e.type === "file" ? `<a href="${apiUrl(state.agent, e.path)}?download=1" title="Descargar">⬇</a>` : ""}</td></tr>`).join("")
  }</tbody></table>`;
  list.querySelectorAll("tr[data-path]").forEach((tr) => tr.addEventListener("click", (ev) => {
    if (ev.target.closest("a")) return;
    const entry = data.entries.find((e) => e.path === tr.dataset.path);
    if (entry.type === "dir") go(state.agent, entry.path);
    else preview(entry);
  }));
}

async function preview(entry) {
  const box = root.querySelector("#wi-preview");
  box.hidden = false;
  const url = apiUrl(state.agent, entry.path);
  const head = `<h2>${esc(entry.path)} <small>· ${size(entry.size)}</small>
    <a class="ghost small" href="${url}?download=1">descargar</a></h2>`;
  if (!TEXTLIKE.test(entry.name) || entry.size > PREVIEW_MAX) {
    box.innerHTML = head + `<p class="meta">${TEXTLIKE.test(entry.name) ? "Demasiado grande para previsualizar" : "Sin vista previa para este tipo"}; descárgalo.</p>`;
    return;
  }
  box.innerHTML = head + '<p class="meta">Cargando…</p>';
  try {
    const r = await fetch(url);
    const text = await r.text();
    box.innerHTML = head + `<pre class="wi-pre">${esc(text)}</pre>`;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    box.innerHTML = head + `<p class="meta error">${esc(e.message)}</p>`;
  }
}

async function upload(files) {
  if (!files.length || !root) return;
  const meta = root.querySelector("#wi-meta");
  for (const file of files) {
    const rel = (state.path ? state.path + "/" : "") + file.name;
    meta.textContent = `Subiendo ${file.name}…`;
    try {
      let r = await fetch(`${apiUrl(state.agent, rel)}`, { method: "PUT", body: file });
      if (r.status === 409 && confirm(`«${file.name}» ya existe. ¿Sustituirlo?`)) {
        r = await fetch(`${apiUrl(state.agent, rel)}?overwrite=1`, { method: "PUT", body: file });
      }
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
    } catch (e) {
      alert(`No se pudo subir ${file.name}: ${e.message}`);
    }
  }
  root.querySelector("#wi-file").value = "";
  await loadAgents();
}

async function copyCurl() {
  const url = location.origin + apiUrl(state.agent, state.path);
  const cmd = `curl ${url}` + String.fromCharCode(10) + `# subir:  curl -T fichero.md ${url}/fichero.md`;
  try { await navigator.clipboard.writeText(cmd); } catch (_) { /* sin portapapeles */ }
  root.querySelector("#wi-meta").textContent = "Copiado: curl " + url;
}
