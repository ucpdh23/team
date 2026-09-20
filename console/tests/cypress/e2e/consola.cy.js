// Prueba de la consola contra el contenedor real. Cypress falla ante cualquier excepción no
// capturada de la página, así que esto también detecta errores de JS.
//
// La vista de Actividad necesita datos para tener algo que dibujar: la prueba se los siembra
// con nombres propios (demo-*) y los borra al final, para no dejar rastro en el histórico
// real del equipo ni depender de que lo haya.
const DEMO = ["demo-uno", "demo-dos", "demo-tres"];

function seed() {
  const now = Date.now();
  const events = [];
  DEMO.forEach((from, i) => {
    const to = DEMO[(i + 1) % DEMO.length];
    for (let n = 0; n < 4; n++) {
      events.push({ ts: now - n * 60000, type: "link.message.sent",
                    agent: from, peer: to, payload: { chars: 100 + n, ok: true } });
      events.push({ ts: now - n * 60000 + 800, type: "link.message.received",
                    agent: to, peer: from, payload: { chars: 100 + n } });
    }
  });
  return cy.request("POST", "/api/events", events);
}

describe("consola team-pi", () => {
  after(() => DEMO.forEach((agent) => cy.request("DELETE", `/api/events?agent=${agent}`)));

  it("Sistema: pinta los contenedores y el estado de la malla", () => {
    cy.visit("/");
    cy.get("nav#tabs a").should("have.length", 3);
    cy.get("nav#tabs a.active").should("contain", "Sistema");
    cy.get("#containers table tbody tr").should("have.length.greaterThan", 0);
    cy.contains("#sys-meta", "contenedores en marcha");
    cy.get("#network").should("not.be.empty");
    cy.contains("#disk", "imágenes", { timeout: 15000 });
    cy.screenshot("1-sistema", { capture: "viewport" });
  });

  it("Actividad: dibuja el grafo y fusiona envío y entrega en una línea", () => {
    seed();
    cy.visit("/#/actividad");
    cy.get("#graph .node", { timeout: 10000 }).should("have.length.greaterThan", 2);
    cy.get("#graph .edge-base").should("have.length.greaterThan", 2);
    // 12 envíos + 12 entregas que deben verse como 12 líneas, no 24. Se cuentan solo las
    // filas de esta prueba: la base puede tener mensajes reales del equipo.
    cy.get("#act-list li").filter(':contains("demo-")').as("demoRows");
    cy.get("@demoRows").should("have.length", 12);
    cy.get("@demoRows").find(".tag").should("have.length", 12).first().should("contain", "✓");
    cy.contains("#act-sub", "mensaje");
    cy.screenshot("2-actividad", { capture: "viewport" });

    cy.get("#act-window button").contains("24 h").click();
    cy.get("#graph .node").should("have.length.greaterThan", 2);
  });

  it("Costes: sigue siendo el dashboard de siempre", () => {
    cy.visit("/#/costes");
    cy.get("#cards", { timeout: 10000 }).should("exist");
    cy.get("canvas#evolution").should("exist");
    cy.get("#range button").should("have.length", 2);
    cy.screenshot("3-costes", { capture: "viewport" });
  });

  it("avisa en Sistema de los avisos del cron sin entregar", () => {
    cy.request("POST", "/api/link/send", { to: "backend", content: "aviso de prueba", job: "demo" })
      .then((res) => {
        cy.visit("/");
        cy.contains("#sys-meta", "aviso(s) del cron pendientes");
        cy.request("POST", "/api/inbox/take", { agent: "backend" });
        cy.request("POST", `/api/inbox/${res.body.id}/ack`);
        cy.request("DELETE", "/api/events?agent=console");
      });
  });

  it("navega entre pestañas sin recargar ni dejar restos", () => {
    cy.visit("/");
    cy.get('nav#tabs a[data-view="actividad"]').click();
    cy.get("#graph").should("exist");
    cy.get('nav#tabs a[data-view="sistema"]').click();
    cy.get("#graph").should("not.exist");
    cy.get("#containers").should("exist");
  });
});
