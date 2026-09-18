"use strict";

// Color fijo por rol, para que el mismo agente sea del mismo color en todas las gráficas.
const ROLE_COLORS = {
  manager: "#6ea8fe",
  backend: "#5ad19a",
  frontend: "#f7b955",
  devops: "#c78bf0",
  cypress: "#ff7a90",
};
const colorFor = (role) => ROLE_COLORS[role] || "#8b93a7";

// Los modelos no se conocen de antemano (dependen del proveedor), así que se colorean por
// posición en la lista `models` (ya ordenada por coste en el servidor).
const MODEL_PALETTE = [
  "#6ea8fe", "#5ad19a", "#f7b955", "#c78bf0", "#ff7a90",
  "#4dd0e1", "#ffd166", "#a3b1c6", "#ef8354", "#7ee787",
];
const modelColor = (i) => MODEL_PALETTE[i % MODEL_PALETTE.length];

const usd = (n) => "$" + (n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = (n) => (n || 0).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
const count = (n) => (n || 0).toLocaleString("en-US");

// Estado del selector: en modo "preset" se usa currentRange (day/week); en modo "dates" se
// usan las fechas de los inputs. Solo uno está activo a la vez.
let mode = "preset";
let currentRange = "day";
const charts = {}; // id -> Chart

Chart.defaults.color = "#9aa2b1";
Chart.defaults.borderColor = "#262b38";
Chart.defaults.font.family = "system-ui, sans-serif";

function buildQuery() {
  if (mode === "dates") {
    const from = document.getElementById("from").value;
    const to = document.getElementById("to").value;
    if (from && to) return `from=${from}&to=${to}`;
  }
  return `range=${currentRange}`;
}

async function load() {
  const meta = document.getElementById("meta");
  meta.textContent = "Cargando…";
  let data;
  try {
    const res = await fetch(`/api/consumption?${buildQuery()}`);
    data = await res.json();
  } catch (e) {
    meta.textContent = "Error al cargar los datos: " + e;
    return;
  }
  if (data.error) { meta.textContent = "Error: " + data.error; return; }

  if (data.empty) {
    meta.textContent = `Sin datos de coste en ${data.cost_dir}`;
    renderCards(data);
    ["evolution", "share", "tokens", "modelCost", "modelCalls"].forEach(destroy);
    return;
  }

  const granularity = data.unit === "hour" ? "por hora" : "por día";
  const windowLabel = data.mode === "dates"
    ? `${data.window} (${granularity})`
    : (data.range === "week" ? "última semana (por día)" : "último día (por hora)");
  meta.textContent = `${data.records} llamadas en total · datos en ${data.cost_dir}`;
  document.getElementById("evo-sub").textContent = "· " + windowLabel;

  renderCards(data);
  renderEvolution(data);
  renderShare(data);
  renderTokens(data);
  renderModelCost(data);
  renderModelCalls(data);
}

function renderCards(data) {
  const el = document.getElementById("cards");
  el.innerHTML = "";
  const roles = Object.keys(data.cost_by_role || {});

  const calls = data.calls_by_role || {};
  el.appendChild(card({
    cls: "total",
    label: "Total del equipo",
    value: usd(data.grand_total),
    sub: `${compact(data.grand_tokens)} tokens · ${count(data.grand_calls)} interacciones`,
  }));

  roles
    .sort((a, b) => data.cost_by_role[b] - data.cost_by_role[a])
    .forEach((role) => {
      el.appendChild(card({
        dot: colorFor(role),
        label: role,
        value: usd(data.cost_by_role[role]),
        sub: `${compact(data.tokens_by_role[role])} tokens · ${count(calls[role])} llamadas`,
      }));
    });
}

function card({ cls, dot, label, value, sub }) {
  const div = document.createElement("div");
  div.className = "card" + (cls ? " " + cls : "");
  div.innerHTML =
    `<div class="label">${dot ? `<span class="dot" style="background:${dot}"></span>` : ""}${label}</div>` +
    `<div class="value">${value}</div>` +
    (sub ? `<div class="sub">${sub}</div>` : "");
  return div;
}

function destroy(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function renderEvolution(data) {
  destroy("evolution");
  const roles = Object.keys(data.series);
  const datasets = roles.map((role) => ({
    label: role,
    data: data.series[role],
    borderColor: colorFor(role),
    backgroundColor: colorFor(role) + "33",
    borderWidth: 2,
    tension: 0.3,
    pointRadius: 0,
    pointHoverRadius: 4,
    fill: true,
  }));
  charts.evolution = new Chart(document.getElementById("evolution"), {
    type: "line",
    data: { labels: data.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        y: { stacked: true, ticks: { callback: (v) => usd(v) }, grid: { color: "#20242f" } },
        x: { stacked: true, grid: { display: false } },
      },
      plugins: {
        legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${usd(c.parsed.y)}` } },
      },
    },
  });
}

function renderShare(data) {
  destroy("share");
  const roles = Object.keys(data.cost_by_role);
  charts.share = new Chart(document.getElementById("share"), {
    type: "doughnut",
    data: {
      labels: roles,
      datasets: [{
        data: roles.map((r) => data.cost_by_role[r]),
        backgroundColor: roles.map(colorFor),
        borderColor: "#171a23",
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "58%",
      plugins: {
        legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } },
        tooltip: { callbacks: { label: (c) => `${c.label}: ${usd(c.parsed)}` } },
      },
    },
  });
}

function renderTokens(data) {
  destroy("tokens");
  const roles = Object.keys(data.tokens_by_role);
  charts.tokens = new Chart(document.getElementById("tokens"), {
    type: "bar",
    data: {
      labels: roles,
      datasets: [{
        data: roles.map((r) => data.tokens_by_role[r]),
        backgroundColor: roles.map(colorFor),
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => compact(c.parsed.y) + " tokens" } },
      },
      scales: {
        y: { ticks: { callback: compact }, grid: { color: "#20242f" } },
        x: { grid: { display: false } },
      },
    },
  });
}

// Barras apiladas: un dataset por modelo, un valor por agente (rol en el eje X). `pick`
// extrae del mapa {rol: {modelo: valor}} el valor de ese modelo para cada rol.
function stackedByModel(canvasId, data, source, fmt) {
  destroy(canvasId);
  const roles = Object.keys(data.cost_by_role);
  const models = data.models || [];
  const byRole = data[source] || {};
  const datasets = models.map((model, i) => ({
    label: model,
    data: roles.map((role) => (byRole[role] || {})[model] || 0),
    backgroundColor: modelColor(i),
    borderRadius: 3,
    stack: "s",
  }));
  charts[canvasId] = new Chart(document.getElementById(canvasId), {
    type: "bar",
    data: { labels: roles, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)}` } },
      },
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: { stacked: true, ticks: { callback: fmt }, grid: { color: "#20242f" } },
      },
    },
  });
}

const renderModelCost = (data) => stackedByModel("modelCost", data, "cost_by_role_model", usd);
const renderModelCalls = (data) => stackedByModel("modelCalls", data, "calls_by_role_model", count);

function setMode(next) {
  mode = next;
  // Resalta el control activo: los presets o la caja de fechas, nunca los dos.
  document.querySelectorAll("#range button").forEach((b) =>
    b.classList.toggle("active", mode === "preset" && b.dataset.range === currentRange));
  document.querySelector(".daterange").classList.toggle("active", mode === "dates");
}

document.getElementById("range").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-range]");
  if (!btn) return;
  currentRange = btn.dataset.range;
  setMode("preset");
  load();
});

document.getElementById("apply").addEventListener("click", () => {
  const from = document.getElementById("from").value;
  const to = document.getElementById("to").value;
  if (!from || !to) {
    document.getElementById("meta").textContent = "Elige fecha de inicio y de fin.";
    return;
  }
  setMode("dates");
  load();
});

document.getElementById("refresh").addEventListener("click", load);

// Inicializa el calendario con el rango de fechas realmente presente en los datos: fija
// min/max de los inputs y los prerrellena, para que al pasar a modo fechas ya haya algo válido.
async function initBounds() {
  try {
    const b = await (await fetch("/api/bounds")).json();
    if (b && !b.empty && b.min && b.max) {
      for (const id of ["from", "to"]) {
        const el = document.getElementById(id);
        el.min = b.min;
        el.max = b.max;
      }
      document.getElementById("from").value = b.min;
      document.getElementById("to").value = b.max;
    }
  } catch (_) { /* si falla, los inputs quedan vacíos; los presets siguen funcionando */ }
}

initBounds().finally(load);
