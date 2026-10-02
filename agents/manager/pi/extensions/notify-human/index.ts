/**
 * notify-human — una tool para pedirle algo al humano, de verdad, no por instrucción.
 *
 * Solo en `manager`: es el único rol que es "el punto de contacto principal" con el humano
 * (ver AGENTS.md), así que es el único al que le hace falta esto hoy.
 *
 * Registra `notify_human` como tool de verdad (`pi.registerTool`), no como un skill: un skill
 * son instrucciones que el modelo puede o no seguir del todo bien (p. ej. "ejecuta este script
 * con el mensaje"); una tool es una llamada con esquema propio que el modelo invoca
 * directamente, sin ningún paso intermedio que se pueda hacer mal.
 *
 * Lo que hace de verdad: un POST a `console/human_notify.py` (vía
 * `POST /api/human-notify`). La consola solo lo encola; convertirlo en una notificación del
 * sistema operativo es cosa de `console/static/app.js`, que sondea con la pestaña de la
 * consola abierta — sin eso abierto, esto no llega a ningún sitio, y la tool se lo dice al
 * agente en el resultado para que no dé el aviso por hecho.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const REQUEST_TIMEOUT_MS = 5000;

export default function (pi: ExtensionAPI) {
  const baseUrl = (process.env.CONSOLE_URL ?? "").trim().replace(/\/+$/, "");
  const self = (process.env.PI_LINK_SELF ?? "manager").trim();
  const token = (process.env.CONSOLE_TOKEN ?? "").trim();

  // Sin consola configurada no hay a quién avisar: ni se registra la tool, igual que
  // team-console se apaga entera sin CONSOLE_URL.
  if (!baseUrl) return;

  pi.registerTool({
    name: "notify_human",
    label: "Avisar al humano",
    description:
      "Pide la atención del humano que dirige el proyecto, fuera de la conversación: le " +
      "llega como una notificación del navegador (requiere tener la consola del equipo " +
      "abierta y haber aceptado el permiso de avisos). Úsalo cuando necesites una decisión, " +
      "una aprobación o una respuesta que solo él puede dar y el trabajo esté bloqueado " +
      "hasta tenerla — no para informar de progreso normal, para eso ya tienes el canal de " +
      "siempre con el resto del equipo.",
    parameters: Type.Object({
      message: Type.String({
        minLength: 1,
        maxLength: 500,
        description:
          "Lo que verá el humano en la notificación: una frase corta y concreta sobre qué " +
          "necesitas de él. No un resumen del trabajo, sino la pregunta o decisión en sí.",
      }),
    }),
    async execute(_toolCallId, params) {
      // Lanzar (no devolver isError) es lo que marca el resultado como fallo de verdad: la
      // documentación de pi es explícita en que devolver un valor nunca activa isError, pase
      // lo que pase dentro de él.
      let response: Response;
      try {
        response = await fetch(`${baseUrl}/api/human-notify`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            ...(token ? { "x-console-token": token } : {}),
          },
          body: JSON.stringify({ agent: self, content: params.message }),
          signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        });
      } catch (error) {
        throw new Error(
          `la consola no respondió (${String(error)}) — dilo también por el canal normal, ` +
          "por si no está mirando el navegador",
        );
      }
      if (!response.ok) {
        const detail = await response.text().catch(() => "");
        throw new Error(
          `la consola rechazó el aviso (HTTP ${response.status}): ${detail.slice(0, 200)}`,
        );
      }
      return {
        content: [{
          type: "text",
          text: "Aviso encolado. Solo le llegará si tiene la consola abierta en el navegador " +
                "y aceptó el permiso de avisos — no asumas que lo ha visto ya.",
        }],
        details: {},
      };
    },
  });
}
