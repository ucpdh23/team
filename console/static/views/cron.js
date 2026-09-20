// Vista Cron: programar los scripts del equipo dentro del contenedor de la consola.
//
// La web programa, no define: se elige un script del catálogo montado (tmp/scripts/, en solo
// lectura) y se le pone una hora. No hay campo de comando libre, y eso es lo que permite que
// la consola no pida autenticación sin que eso signifique ejecución arbitraria para quien
// alcance el puerto.

const REFRESH_MS = 10000;
const STATUS = {
  ok: { label: "ok", cls: "up" },
  error: { label: "error", cls: "down" },
  timeout: { label: "timeout", cls: "down" },
  skipped: { label: "saltado", cls: "" },
  running: { label: "en curso", cls: "" },
};

let root = null, timer = null, scripts = [], openJob = null;

const MARKUP = `
  <div class="view-head">
    <p class="meta" id="cron-meta">Cargando…</p>
    <div class="controls"><button id="cron-new" class="ghost">+ Programar</button></div>
  </div>
  <section class="panel" id="cron-form-panel" hidden></section>
  <section class="panel">
    <h2>Programaciones</h2>
    <div id="cron-jobs"></div>
  </section>
  <section class="grid">
    <div class="panel">
      <h2>Historial <small id="cron-runs-sub"></small></h2>
      <div id="cron-runs"></div>
    </div>
    <div class="panel">
      <h2>Avisos pendientes de entregar <small>· a los agentes</small></h2>
      <div id="cron-inbox"></div>
    </div>
  </section>
`;

export async function mount(container) {
  root = container;
  container.innerHTML = MARKUP;
  container.querySelector("#cron-new").addEventListener("click", toggleForm);
  await Promise.all([loadScripts(), refresh()]);
  timer = setInterval(() => { if (document.visibilityState === "visible") refresh(); }, REFRESH_MS);
}

export function unmount() {
  clearInterval(timer);
  timer = null; root = null; openJob = null; scripts = [];
}

const time = (ts) => (ts ? new Date(ts).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "medium" }) : "—");
const secs = (ms) => (ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

async function loadScripts() {
  try {
    const data = await api("/api/cron/scripts");
    scripts = data.scripts || [];
    root.querySelector("#cron-meta").dataset.dir = data.dir;
  } catch (e) { scripts = []; }
}

async function refresh() {
  try {
    const [jobs, inbox] = await Promise.all([api("/api/cron/jobs"), api("/api/inbox")]);
    if (!root) return;
    renderJobs(jobs);
    renderInbox(inbox.pending || []);
    await loadRuns();
  } catch (e) {
    if (root) root.querySelector("#cron-meta").textContent = "No se pudo consultar el cron: " + e;
  }
}

function renderJobs(data) {
  const stats = data.stats || {};
  const dir = root.querySelector("#cron-meta").dataset.dir || "";
  root.querySelector("#cron-meta").textContent =
    `${stats.enabled}/${stats.jobs} programaciones activas · ${stats.scripts} script(s) en ${dir}` +
    (stats.failed_last_day ? ` · ${stats.failed_last_day} fallo(s) en 24 h` : "") +
    // Las horas de abajo las pinta tu navegador; los disparos los decide el contenedor.
    ` · horario del cron: ${stats.timezone} (ahora ${stats.now})`;

  const jobs = data.jobs || [];
  if (!jobs.length) {
    root.querySelector("#cron-jobs").innerHTML = scripts.length
      ? '<p class="meta">Todavía no hay nada programado. Usa «+ Programar».</p>'
      : `<p class="meta">No hay scripts publicados en <code>${dir}</code>. Los scripts son del
         equipo de desarrollo y no se versionan en team: déjalos ahí y aparecerán aquí.</p>`;
    return;
  }

  root.querySelector("#cron-jobs").innerHTML = `<table class="table">
    <thead><tr><th></th><th>job</th><th>cuándo</th><th>script</th>
      <th>última</th><th>siguiente</th><th></th></tr></thead>
    <tbody>${jobs.map((job) => {
      const last = job.last_run;
      const status = last ? (STATUS[last.status] || { label: last.status, cls: "" }) : null;
      return `<tr class="${job.enabled ? "" : "down"}" data-id="${job.id}">
        <td><input type="checkbox" ${job.enabled ? "checked" : ""} data-action="toggle"
             title="Activar o pausar"></td>
        <td>${job.name}</td>
        <td class="mono">${job.schedule}</td>
        <td class="dim">${job.script}${job.args.length ? " " + job.args.join(" ") : ""}</td>
        <td>${last ? `<span class="state ${status.cls}">${status.label}</span>
              <span class="dim">${time(last.started_ts)}</span>` : "<span class='dim'>nunca</span>"}</td>
        <td class="dim">${job.enabled ? time(job.next_run_ts) : "pausado"}</td>
        <td class="num">
          <button class="ghost small" data-action="run" title="Ejecutar ahora">▶</button>
          <button class="ghost small" data-action="history" title="Ver historial">☰</button>
          <button class="ghost small" data-action="delete" title="Borrar">✕</button>
        </td>
      </tr>`;
    }).join("")}</tbody></table>`;

  root.querySelector("#cron-jobs").onclick = onJobAction;
  root.querySelector("#cron-jobs").onchange = onJobAction;
}

async function onJobAction(event) {
  const row = event.target.closest("tr[data-id]");
  const action = event.target.dataset.action;
  if (!row || !action) return;
  const id = row.dataset.id;
  try {
    if (action === "run") {
      await api(`/api/cron/jobs/${id}/run`, { method: "POST" });
      openJob = id;
      // La ejecución es asíncrona: se refresca un instante después para ver ya el resultado.
      setTimeout(refresh, 1200);
    } else if (action === "toggle") {
      await api(`/api/cron/jobs/${id}`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: event.target.checked }),
      });
      refresh();
    } else if (action === "history") {
      openJob = openJob === id ? null : id;
      loadRuns();
    } else if (action === "delete") {
      if (!confirm("¿Borrar esta programación? El script no se toca.")) return;
      await api(`/api/cron/jobs/${id}`, { method: "DELETE" });
      if (openJob === id) openJob = null;
      refresh();
    }
  } catch (e) {
    alert("No se pudo: " + e.message);
  }
}

async function loadRuns() {
  try {
    const data = await api(openJob ? `/api/cron/jobs/${openJob}/runs` : "/api/cron/runs?limit=25");
    if (!root) return;
    root.querySelector("#cron-runs-sub").textContent = openJob
      ? "· solo el job seleccionado" : "· todas las programaciones";
    const runs = data.runs || [];
    root.querySelector("#cron-runs").innerHTML = runs.length
      ? `<ul class="events">${runs.map((run) => {
          const status = STATUS[run.status] || { label: run.status, cls: "" };
          return `<li>
            <span class="mono dim">${time(run.started_ts)}</span>
            <span class="state ${status.cls}">${status.label}</span>
            ${run.job_name}
            <span class="dim">${secs(run.finished_ts ? run.finished_ts - run.started_ts : null)}</span>
            <button class="ghost small" data-run="${run.id}" title="Ver salida">salida</button>
          </li>`;
        }).join("")}</ul>`
      : '<p class="meta">Sin ejecuciones registradas.</p>';
    root.querySelector("#cron-runs").onclick = async (event) => {
      const id = event.target.dataset.run;
      if (!id) return;
      const detail = await api(`/api/cron/runs/${id}`);
      showOutput(detail);
    };
  } catch (_) { /* el refresco siguiente lo reintenta */ }
}

function showOutput(run) {
  const panel = root.querySelector("#cron-runs");
  const existing = panel.querySelector(".run-output");
  if (existing) existing.remove();
  const box = document.createElement("pre");
  box.className = "run-output";
  box.textContent = run.output || "(sin salida)";
  panel.appendChild(box);
}

function renderInbox(pending) {
  root.querySelector("#cron-inbox").innerHTML = pending.length
    ? `<ul class="events">${pending.map((note) => `<li>
        <span class="mono dim">${Math.round(note.age_s / 60)} min</span>
        para <strong>${note.agent}</strong>
        <span class="dim">${note.job ? "· " + note.job : ""} · ${note.chars} car.</span>
        ${note.attempts > 1 ? '<span class="tag bad">reintentado</span>' : ""}
      </li>`).join("")}</ul>`
    : `<p class="meta">Nada pendiente: todo lo enviado a los agentes se ha entregado.</p>`;
}

// ── Formulario ──────────────────────────────────────────────────────────────

function toggleForm() {
  const panel = root.querySelector("#cron-form-panel");
  panel.hidden = !panel.hidden;
  if (panel.hidden) return;
  panel.innerHTML = `
    <h2>Nueva programación</h2>
    <div class="form">
      <label>Nombre <input id="f-name" placeholder="aviso-tickets-manager"></label>
      <label>Cuándo <input id="f-schedule" class="mono" value="0 20 * * 1-5"></label>
      <label>Script
        <select id="f-script">${scripts.map((s) =>
          `<option value="${s.name}">${s.name}${s.description ? " — " + s.description : ""}</option>`
        ).join("")}</select>
      </label>
      <label>Argumentos <input id="f-args" placeholder="opcional, separados por espacios"></label>
      <label>Timeout (s) <input id="f-timeout" type="number" value="300" min="1" max="3600"></label>
      <button id="f-save" class="ghost">Guardar</button>
      <p class="meta" id="f-error"></p>
    </div>
    <p class="meta">Formato: <span class="mono">minuto hora día-del-mes mes día-de-semana</span>
       — <span class="mono">0 20 * * 1-5</span> es a las 20:00 de lunes a viernes.</p>`;
  panel.querySelector("#f-save").addEventListener("click", save);
}

async function save() {
  const value = (id) => root.querySelector(id).value.trim();
  const error = root.querySelector("#f-error");
  error.textContent = "";
  try {
    await api("/api/cron/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: value("#f-name"),
        schedule: value("#f-schedule"),
        script: value("#f-script"),
        args: value("#f-args") ? value("#f-args").split(/\s+/) : [],
        timeout_s: Number(value("#f-timeout")) || 300,
      }),
    });
    root.querySelector("#cron-form-panel").hidden = true;
    refresh();
  } catch (e) {
    // El servidor ya explica por qué no vale (la expresión, el script, el nombre repetido):
    // se enseña tal cual en vez de traducirlo a un "error de validación" genérico.
    error.textContent = e.message;
  }
}
