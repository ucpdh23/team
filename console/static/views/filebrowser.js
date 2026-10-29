// Explorador de ficheros de la consola: navegar un árbol por ámbitos (agentes), leer sus
// documentos, subir ficheros y, si la vista lo pide, editarlos. Lo usan Workitems y Skills
// (workitems.js y skills.js solo dicen qué API y qué textos); es la cara web de
// /api/workitems y /api/skills, y el botón «curl» da la orden equivalente.
//
// Solo hay una vista montada a la vez, así que el estado es del módulo y `mount` lo
// configura con `cfg`: { base, hash, rootLabel(scope), missing(scope), editable, flat }.

const PREVIEW_MAX = 512 * 1024;
const TEXTLIKE = /\.(md|markdown|txt|log|json|ya?ml|toml|ini|csv|xml|html?|css|svg|js|ts|tsx|py|java|kt|sh|sql|feature|properties|gradle|env)$/i;

let root = null, cfg = null, agents = [], state = { agent: null, path: "" };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const enc = (path) => path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
const apiUrl = (agent, path) => `${cfg.base}${cfg.flat ? "" : "/" + agent}${path ? "/" + enc(path) : ""}`;
const size = (n) => n == null ? "" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
const when = (ts) => new Date(ts).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });

const MARKUP = `
  <div class="view-head">
    <p class="meta" id="wi-meta">Cargando…</p>
    <div class="controls">
      <button id="wi-curl" class="ghost small" title="Copia el curl equivalente a lo que estás viendo">curl</button>
      <button id="wi-mkdir" class="ghost">📁 Nueva carpeta</button>
      <button id="wi-upload" class="ghost">⬆ Subir</button>
      <input type="file" id="wi-file" multiple hidden />
    </div>
  </div>
  <div class="wi-split">
    <section class="panel">
      <div id="wi-agents" class="segmented"></div>
      <p id="wi-crumbs" class="meta"></p>
      <div id="wi-list"></div>
    </section>
    <section class="panel wi-viewer" id="wi-preview" hidden></section>
  </div>
`;

export async function mount(container, config) {
  root = container;
  cfg = config;
  container.innerHTML = MARKUP;
  const q = new URLSearchParams((location.hash.split("?")[1]) || "");
  state = { agent: q.get("agent"), path: q.get("path") || "" };
  container.querySelector("#wi-upload").addEventListener("click", () => container.querySelector("#wi-file").click());
  container.querySelector("#wi-mkdir").addEventListener("click", makeFolder);
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
  document.addEventListener("keydown", onKey);
  await loadAgents();
}

export function unmount() {
  document.removeEventListener("keydown", onKey);
  root = null; cfg = null; agents = []; previewEntry = null;
}

async function getJson(url, options) {
  const r = await fetch(url, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

async function loadAgents() {
  if (cfg.flat) {
    agents = [{ agent: cfg.scope || "docs", exists: true, items: null }];
  } else {
    const index = await getJson(cfg.base);
    // workitems responde {agents:[{agent,…}]}, skills {scopes:[{scope,…}]}: se unifica aquí.
    agents = (index.agents || index.scopes).map((a) => ({ ...a, agent: a.agent ?? a.scope }));
  }
  if (!root) return;
  if (!state.agent || !agents.some((a) => a.agent === state.agent)) {
    state = { agent: (agents.find((a) => a.exists) || agents[0]).agent, path: "" };
  }
  const bar = root.querySelector("#wi-agents");
  bar.hidden = !!cfg.flat;
  bar.style.display = cfg.flat ? "none" : "";
  bar.innerHTML = agents.map((a) =>
    `<button data-agent="${a.agent}" class="${a.agent === state.agent ? "active" : ""}" ${a.exists ? "" : 'title="no existe todavía"'}>${a.agent}${a.exists ? ` · ${a.items}` : ""}</button>`).join("");
  bar.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => go(b.dataset.agent, "")));
  await go(state.agent, state.path);
}

function setHash() {
  const q = new URLSearchParams({ agent: state.agent });
  if (state.path) q.set("path", state.path);
  history.replaceState(null, "", `#/${cfg.hash}?${q}`);
}

async function go(agent, path) {
  if (!root) return;
  state = { agent, path };
  setHash();
  root.querySelectorAll("#wi-agents button").forEach((b) => b.classList.toggle("active", b.dataset.agent === agent));
  const list = root.querySelector("#wi-list");
  const info = agents.find((a) => a.agent === agent);
  renderCrumbs();
  if (info && !info.exists) {
    list.innerHTML = `<p class="meta">${cfg.missing(agent)}</p>`;
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
  const links = [`<a href="#" data-path="">${esc(cfg.rootLabel(state.agent))}</a>`].concat(parts.map((p) => {
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
    `${dirs} carpeta(s), ${data.entries.length - dirs} fichero(s) · arrastra ficheros aquí para subirlos${cfg.editable ? " o edítalos con ✎" : ""}`;
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

// ── Visor ────────────────────────────────────────────────────────────────────
//
// Se abre a la derecha del listado. Según el tipo: Markdown renderizado (con diagramas
// mermaid), imagen, o texto tal cual. Markdown, DOMPurify y Mermaid vienen de un CDN con la
// versión fijada, como Chart.js: hace falta red en el navegador la primera vez, y sin ella
// el Markdown se enseña como texto.

const CDN = {
  marked: "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js",
  purify: "https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js",
  mermaid: "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js",
};
const IMAGE = /\.(png|jpe?g|gif|webp|bmp|ico|avif|svg)$/i;
const MARKDOWN = /\.(md|markdown)$/i;
const MERMAID = /\.(mmd|mermaid)$/i;
const loaded = {};

function loadScript(name) {
  if (!loaded[name]) {
    loaded[name] = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = CDN[name];
      s.onload = resolve;
      s.onerror = () => { delete loaded[name]; s.remove(); reject(new Error(`no se pudo cargar ${name} (¿hay red?)`)); };
      document.head.appendChild(s);
    });
  }
  return loaded[name];
}

// Resuelve una ruta relativa (con ./ y ../) contra la carpeta del documento. null si se sale.
function resolveRel(baseDir, rel) {
  const out = baseDir.split("/").filter(Boolean);
  for (const part of decodeURIComponent(rel.split(/[?#]/)[0]).split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") { if (!out.length) return null; out.pop(); } else out.push(part);
  }
  return out.join("/");
}

let previewEntry = null, previewMode = "rendered";

function toggleFull(force) {
  const box = root?.querySelector("#wi-preview");
  if (!box) return;
  const on = force ?? !box.classList.contains("full");
  box.classList.toggle("full", on);
  const b = box.querySelector("#wi-full");
  if (b) b.textContent = on ? "✕ Cerrar" : "⛶ Pantalla completa";
}

function onKey(e) { if (e.key === "Escape") toggleFull(false); }

async function preview(entry) {
  previewEntry = entry;
  const box = root.querySelector("#wi-preview");
  box.hidden = false;
  const url = apiUrl(state.agent, entry.path);
  const isMd = MARKDOWN.test(entry.name) || MERMAID.test(entry.name);
  const full = box.classList.contains("full");
  box.innerHTML = `<h2>${esc(entry.path)} <small>${entry.size == null ? "" : "· " + size(entry.size)}</small></h2>
    <div class="wi-tools">
      ${isMd ? `<span class="segmented"><button data-mode="rendered" class="${previewMode === "rendered" ? "active" : ""}">Vista</button><button data-mode="source" class="${previewMode === "source" ? "active" : ""}">Fuente</button></span>` : ""}
      <a class="ghost small" href="${url}?download=1">⬇ descargar</a>
      ${cfg.editable && TEXTLIKE.test(entry.name) ? '<button id="wi-edit" class="ghost small">✎ Editar</button>' : ""}
      <button id="wi-full" class="ghost small">${full ? "✕ Cerrar" : "⛶ Pantalla completa"}</button>
    </div>
    <div id="wi-body" class="wi-body"><p class="meta">Cargando…</p></div>`;
  box.querySelector("#wi-full").addEventListener("click", () => toggleFull());
  box.querySelector("#wi-edit")?.addEventListener("click", () => edit(entry, box.querySelector("#wi-body")));
  box.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    previewMode = b.dataset.mode; preview(entry);
  }));
  const body = box.querySelector("#wi-body");
  const current = () => previewEntry === entry && root;   // el usuario pudo abrir otro mientras tanto

  try {
    if (IMAGE.test(entry.name)) {
      // Por blob, con el tipo que toca: el servidor entrega el SVG como text/plain (para que
      // abrirlo en una pestaña no ejecute nada) y así <img> sigue pudiendo dibujarlo, sin scripts.
      const blob = await (await fetch(url)).blob();
      if (!current()) return;
      const typed = /\.svg$/i.test(entry.name) ? new Blob([blob], { type: "image/svg+xml" }) : blob;
      body.innerHTML = '<img class="wi-img" alt="" />';
      body.querySelector("img").src = URL.createObjectURL(typed);
      return;
    }
    if (!TEXTLIKE.test(entry.name)) {
      body.innerHTML = '<p class="meta">Sin vista previa para este tipo; descárgalo.</p>';
      return;
    }
    if (entry.size != null && entry.size > PREVIEW_MAX) {
      body.innerHTML = '<p class="meta">Demasiado grande para previsualizar; descárgalo.</p>';
      return;
    }
    const text = await (await fetch(url)).text();
    if (!current()) return;
    if (isMd && previewMode === "rendered") {
      try { await renderMarkdown(body, text, entry); return; }
      catch (e) { body.innerHTML = `<p class="meta error">${esc(e.message)} — se muestra el fuente.</p><pre class="wi-pre">${esc(text)}</pre>`; return; }
    }
    body.innerHTML = `<pre class="wi-pre">${esc(text)}</pre>`;
  } catch (e) {
    if (current()) body.innerHTML = `<p class="meta error">${esc(e.message)}</p>`;
  }
}

async function renderMarkdown(body, text, entry) {
  const dir = entry.path.split("/").slice(0, -1).join("/");
  const source = MERMAID.test(entry.name) ? "```mermaid\n" + text + "\n```" : text;
  await Promise.all([loadScript("marked"), loadScript("purify")]);
  const html = window.DOMPurify.sanitize(window.marked.parse(source, { gfm: true }));
  body.innerHTML = `<div class="md">${html}</div>`;
  const md = body.querySelector(".md");

  // Imágenes y enlaces relativos apuntan a otros ficheros del mismo workitem.
  const isRelative = (v) => v && !/^([a-z][a-z0-9+.-]*:|\/|#)/i.test(v);
  md.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src");
    if (!isRelative(src)) return;
    const target = resolveRel(dir, src);
    if (target != null) img.src = apiUrl(state.agent, target);
  });
  md.querySelectorAll("a").forEach((a) => {
    const href = a.getAttribute("href");
    if (isRelative(href)) {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const target = resolveRel(dir, href);
        if (target != null) preview({ path: target, name: target.split("/").pop(), size: null });
      });
    } else if (href && !href.startsWith("#")) {
      a.target = "_blank"; a.rel = "noopener noreferrer";
    }
  });

  const blocks = [...md.querySelectorAll("pre > code.language-mermaid")];
  if (!blocks.length) return;
  await loadScript("mermaid");
  window.mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
  for (const code of blocks) {
    const holder = document.createElement("div");
    holder.className = "mermaid-box";
    try {
      const { svg } = await window.mermaid.render(`mmd-${Math.random().toString(36).slice(2)}`, code.textContent);
      holder.innerHTML = svg;
    } catch (e) {
      // Un diagrama roto no tumba el documento: se deja el código con el motivo.
      holder.innerHTML = `<p class="meta error">Diagrama mermaid no válido: ${esc(String(e.message || e).split("\n")[0])}</p><pre class="wi-pre">${esc(code.textContent)}</pre>`;
    }
    code.parentElement.replaceWith(holder);
  }
  // mermaid deja nodos auxiliares en <body> si falla un render.
  document.querySelectorAll('body > [id^="dmmd-"]').forEach((n) => n.remove());
}

async function edit(entry, body) {
  body.innerHTML = '<p class="meta">Cargando…</p>';
  let text;
  try { text = await (await fetch(apiUrl(state.agent, entry.path))).text(); }
  catch (e) { body.innerHTML = `<p class="meta error">${esc(e.message)}</p>`; return; }
  body.innerHTML = `<textarea class="wi-edit" spellcheck="false"></textarea>
    <div class="wi-tools"><button id="wi-save" class="ghost">Guardar</button>
    <button id="wi-cancel" class="ghost">Cancelar</button><span class="meta" id="wi-edit-msg"></span></div>`;
  const area = body.querySelector("textarea");
  area.value = text;
  body.querySelector("#wi-cancel").addEventListener("click", () => preview({ ...entry, size: null }));
  body.querySelector("#wi-save").addEventListener("click", async () => {
    const msg = body.querySelector("#wi-edit-msg");
    msg.textContent = "Guardando…";
    try {
      const r = await fetch(`${apiUrl(state.agent, entry.path)}?overwrite=1`, { method: "PUT", body: area.value });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
      await preview({ ...entry, size: new Blob([area.value]).size });
    } catch (e) { msg.textContent = `No se pudo guardar: ${e.message}`; }
  });
}

async function makeFolder() {
  const name = prompt("Nombre de la nueva carpeta:");
  if (name == null) return;
  const clean = name.trim();
  if (!clean) return;
  if ([".", ".."].includes(clean) || /[\\/\\\\\x00]/.test(clean)) {
    alert("Usa un nombre de carpeta simple, sin / ni \\\\.");
    return;
  }
  const path = (state.path ? state.path + "/" : "") + clean;
  try {
    const response = await fetch(apiUrl(state.agent, path), { method: "POST" });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || `HTTP ${response.status}`);
    await loadAgents();
  } catch (e) {
    alert(`No se pudo crear la carpeta: ${e.message}`);
  }
}

async function upload(files) {
  if (!files.length || !root) return;
  const meta = root.querySelector("#wi-meta");
  for (const file of files) {
    const rel = (state.path ? state.path + "/" : "") + file.name;
    meta.textContent = `Subiendo ${file.name}…`;
    try {
      // overwrite=0 explícito: la API de skills sustituye por defecto, pero desde la web no
      // se pisa nada sin preguntar.
      let r = await fetch(`${apiUrl(state.agent, rel)}?overwrite=0`, { method: "PUT", body: file });
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
