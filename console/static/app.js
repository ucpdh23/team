// Router de la consola: una página, varias vistas.
//
// Cada vista es un módulo con `mount(container)` y, opcionalmente, `unmount()`. El router
// solo decide cuál está puesta; ninguna vista sabe de las demás. `unmount()` es obligatorio
// para lo que siga vivo fuera de la pantalla (temporizadores, gráficas de Chart.js,
// animaciones): sin eso, cambiar de pestaña dejaría relojes corriendo de fondo.

const VIEWS = {
  sistema: () => import("/views/sistema.js"),
  actividad: () => import("/views/actividad.js"),
  costes: () => import("/views/costes.js"),
  cron: () => import("/views/cron.js"),
  tmux: () => import("/views/tmux.js"),
};
const DEFAULT_VIEW = "sistema";

const container = document.getElementById("view");
let current = null;

function viewFromHash() {
  const name = (location.hash || "").replace(/^#\/?/, "").split("?")[0];
  return VIEWS[name] ? name : DEFAULT_VIEW;
}

async function render() {
  const name = viewFromHash();
  if (current && current.name === name) return;

  if (current?.module?.unmount) {
    try { current.module.unmount(); } catch (e) { console.error("unmount", e); }
  }
  container.innerHTML = '<p class="meta">Cargando…</p>';
  document.querySelectorAll("#tabs a").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === name));

  try {
    const module = await VIEWS[name]();
    current = { name, module };
    await module.mount(container);
  } catch (e) {
    console.error(e);
    container.innerHTML = `<p class="meta error">No se pudo cargar la vista «${name}»: ${e}</p>`;
  }
}

window.addEventListener("hashchange", render);
render();

// El prefijo del cluster en la cabecera: con varios docker compose de team en la misma
// máquina, saber en cuál estás mirando no es un adorno.
fetch("/api/health")
  .then((r) => r.json())
  .then((h) => {
    const name = h.project || h.prefix;
    if (name) document.getElementById("cluster").textContent = `· consola · ${name}`;
    // El título de la pestaña es el CONTAINER_PREFIX, no el nombre de proyecto de Compose: es
    // el que de verdad elige y controla quien levanta el cluster (ver README, "Publicando
    // ella, y varios clusters en una máquina").
    if (h.prefix) document.title = `${h.prefix} · consola`;
  })
  .catch(() => {});

// ── Avisos del sistema operativo ─────────────────────────────────────────────
//
// Un agente (hoy, la tool `notify_human` del manager — ver agents/manager/pi/extensions/
// notify-human/) puede pedir que algo le llegue al humano. La consola solo lo encola
// (console/human_notify.py); convertirlo en una notificación real es cosa de esta pestaña,
// así que hace falta tenerla abierta — no hace falta que esté en primer plano ni que la vista
// activa sea ninguna en concreto, por eso este sondeo vive aquí y no en una vista.
//
// Sin permiso del navegador no hay nada que avisar, así que ni se sondea: pedirlo requiere un
// gesto real del usuario (un clic), los navegadores ignoran la petición si no.

const NOTIF_POLL_MS = 5000;
const notifButton = document.getElementById("notif-toggle");
let notifCursor = null;
let notifTimer = null;

function notifSupported() {
  return "Notification" in window;
}

function refreshNotifButton() {
  if (!notifButton) return;
  if (!notifSupported()) {
    notifButton.textContent = "avisos: no soportados";
    notifButton.disabled = true;
    return;
  }
  const state = Notification.permission;
  notifButton.textContent =
    state === "granted" ? "avisos: activos" :
    state === "denied" ? "avisos: bloqueados por el navegador" : "avisos: activar";
  notifButton.disabled = state !== "default";
}

async function pollNotices() {
  try {
    const url = notifCursor == null ? "/api/human-notify" : `/api/human-notify?since=${notifCursor}`;
    const data = await (await fetch(url)).json();
    notifCursor = data.cursor;
    for (const notice of data.notices || []) {
      // tag = id: si el mismo aviso llega dos veces (un reintento tras perder la respuesta),
      // el navegador sustituye el toast en vez de apilar uno igual.
      new Notification(`team-pi · ${notice.agent}`, { body: notice.content, tag: notice.id,
                                                       icon: "/favicon.svg" });
    }
  } catch (_) { /* el siguiente sondeo lo reintenta */ }
}

function maybeStartPolling() {
  if (notifTimer || !notifSupported() || Notification.permission !== "granted") return;
  pollNotices();
  notifTimer = setInterval(pollNotices, NOTIF_POLL_MS);
}

if (notifButton) {
  refreshNotifButton();
  maybeStartPolling();
  notifButton.addEventListener("click", async () => {
    if (!notifSupported() || Notification.permission !== "default") return;
    await Notification.requestPermission();
    refreshNotifButton();
    maybeStartPolling();
  });
}
