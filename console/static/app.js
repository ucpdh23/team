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
  })
  .catch(() => {});
