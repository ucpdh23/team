// Terminal interactiva de la pestaña Tmux (console/terminal.py, console/static/terminal.js).
//
// A propósito NO teclea nada: esta prueba puede correr contra un equipo real, y lo tecleado
// llegaría a un `pi` de verdad (hasta un Esc interrumpe lo que esté haciendo). Comprueba que la
// terminal se abre con lo que manda el servidor, que se distingue como modo escritura y que se
// vuelve a solo lectura. Que las teclas llegan y que la limpieza deja tmux sin clientes se
// prueba fuera, contra un agente desechable.
//
// Sin CONSOLE_TOKEN la terminal no existe, y lo que se comprueba es que el botón lo diga en
// vez de fallar. Para probar la terminal en sí: `--env CONSOLE_TOKEN=<token de la consola>`.
const TOKEN = Cypress.env("CONSOLE_TOKEN") || "";

describe("terminal tmux", () => {
  beforeEach(() => { if (TOKEN) cy.setCookie("console_token", TOKEN); });

  it("«Escribir» abre una terminal real y se puede volver a solo lectura", () => {
    cy.request({ url: "/api/tmux/panes", headers: TOKEN ? { "X-Console-Token": TOKEN } : {} })
      .then((res) => {
        const vivos = res.body.agents.filter((a) => a.state === "running");
        if (!vivos.length) return;   // sin agentes levantados no hay terminal que abrir
        const { enabled, reason } = res.body.interactive;

        cy.visit("/#/tmux");
        cy.get(`.tmux-cell[data-agent="${vivos[0].agent}"] .tmux-scale`).click();
        cy.get("#tmux-modal").should("be.visible");

        if (!enabled) {
          cy.get("#tmux-modal-write").should("be.disabled");
          cy.get("#tmux-modal-hint").should("contain", reason);
          return;
        }

        cy.get("#tmux-modal-write").click();
        cy.get("#tmux-modal-live", { timeout: 20000 }).should("be.visible");
        cy.get("#tmux-modal.writing").should("exist");
        cy.get("#tmux-modal-term .xterm", { timeout: 20000 }).should("exist");
        cy.get("#tmux-modal-body").should("not.be.visible");
        // tmux dibuja tras conectar (como mínimo su barra de estado): esperar a que haya algo
        // pintado evita fotografiar una terminal todavía en blanco.
        cy.get("#tmux-modal-term .xterm-rows").should(($rows) => {
          expect($rows.text().trim()).to.not.equal("");
        });
        cy.screenshot("6-terminal", { capture: "viewport" });

        cy.get("#tmux-modal-write").should("contain", "Solo lectura").click();
        cy.get("#tmux-modal-term").should("not.be.visible");
        cy.get("#tmux-modal-live").should("not.be.visible");
        cy.get("#tmux-modal.writing").should("not.exist");
        cy.get("#tmux-modal-body").should("be.visible");
      });
  });
});
