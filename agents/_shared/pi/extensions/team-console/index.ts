/**
 * team-console — observa la conversación del equipo y se la cuenta a la consola.
 *
 * Una sola copia para los 5 roles: docker-compose.yml la monta dentro del directorio de
 * extensiones de cada agente (montaje anidado sobre ./agents/<rol>/pi/extensions), y pi la
 * descubre porque busca también en `~/.pi/agent/extensions/<dir>/index.ts`.
 *
 * Qué emite:
 *   - link.message.sent      cuando este agente usa link_send (fuente principal: trae el
 *                            destinatario exacto y el instante real del envío)
 *   - link.message.received  cuando pi-link entrega mensajes a este agente (aporta la
 *                            latencia de entrega y cubre a quien no tenga esta extensión)
 *
 * Qué NO emite: el texto de los mensajes. Solo quién, a quién y cuánto ocupaba. Por la malla
 * viajan fragmentos de código y rutas de los proyectos en los que trabajan los agentes, y
 * nada de eso tiene por qué acabar en una base de datos de observabilidad.
 *
 * Regla de oro: esto corre DENTRO del proceso `pi` del agente. Si la consola está caída, va
 * lenta o devuelve un error, el agente no puede enterarse. De ahí la cola acotada, el timeout
 * corto, el backoff y el silencio absoluto en su interfaz.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";

// Tope de la cola en memoria. Al desbordar se tira lo más viejo y se cuenta: la consola
// preferirá saber que perdió N eventos a enseñar un grafo incompleto como si estuviera bien.
const MAX_QUEUE = 500;
// Ventana de agrupación: varios eventos seguidos (una ráfaga de mensajes) viajan en un POST.
const FLUSH_DELAY_MS = 500;
const MAX_BATCH = 100;
const REQUEST_TIMEOUT_MS = 2000;
const BACKOFF_MIN_MS = 2000;
const BACKOFF_MAX_MS = 30000;

type Event = {
  id: string;
  ts: number;
  type: string;
  agent: string;
  peer: string | null;
  payload: Record<string, unknown>;
};

export default function (pi: ExtensionAPI) {
  const baseUrl = (process.env.CONSOLE_URL ?? "").trim().replace(/\/+$/, "");
  const self = (process.env.PI_LINK_SELF ?? "").trim();

  // Sin consola configurada la extensión no existe: ni cola, ni temporizadores, ni handlers.
  // Es lo que permite apagarla entera con CONSOLE_URL= en .env.
  if (!baseUrl || !self) return;

  const endpoint = `${baseUrl}/api/events`;
  const queue: Event[] = [];
  // Destinatario de cada link_send en vuelo: tool_execution_end NO trae los argumentos de la
  // llamada (solo toolCallId, toolName, result e isError), así que hay que recordarlos.
  const pending = new Map<string, { to: string; chars: number }>();
  let dropped = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let backoff = BACKOFF_MIN_MS;

  // ── Cola ──────────────────────────────────────────────────────────────────

  function enqueue(type: string, peer: string | null, payload: Record<string, unknown> = {}) {
    if (queue.length >= MAX_QUEUE) {
      queue.shift();
      dropped++;
    }
    queue.push({ id: randomUUID(), ts: Date.now(), type, agent: self, peer, payload });
    schedule(FLUSH_DELAY_MS);
  }

  function schedule(delay: number) {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      void flush();
    }, delay);
  }

  async function flush(): Promise<void> {
    if (queue.length === 0) return;
    const batch = queue.splice(0, MAX_BATCH);
    if (dropped > 0) {
      // Viaja con el siguiente lote en vez de en un evento propio: así la consola puede
      // avisar de que este agente perdió eventos sin inventarse una conversación.
      batch[0].payload = { ...batch[0].payload, dropped };
      dropped = 0;
    }

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(batch),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      backoff = BACKOFF_MIN_MS;
      if (queue.length > 0) schedule(FLUSH_DELAY_MS);
    } catch {
      // Los eventos vuelven al principio de la cola para no perder el orden, y se reintenta
      // con backoff. Nada se escribe en disco: si el agente se reinicia se pierde lo
      // pendiente, y es aceptable — son datos de observabilidad, no la verdad de nada.
      queue.unshift(...batch);
      if (queue.length > MAX_QUEUE) {
        dropped += queue.length - MAX_QUEUE;
        queue.length = MAX_QUEUE;
      }
      schedule(backoff);
      backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
    }
  }

  // ── Lectura de los mensajes entrantes ─────────────────────────────────────

  function contentToText(content: unknown): string {
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      return content
        .map((part: any) => (part && part.type === "text" ? String(part.text ?? "") : ""))
        .join("\n");
    }
    return "";
  }

  /**
   * Trocea un mensaje de pi-link en los mensajes lógicos que lleva dentro.
   *
   * pi-link agrupa los entrantes (hasta 20 mensajes o ~16.000 caracteres en una ventana de
   * 200 ms) en un único mensaje cuyo texto es `[Link: N message(s) received]` seguido de un
   * bloque `From "<nombre>":` por remitente — el nombre NO viene en `details`, que solo trae
   * `{batched, count}`. De ahí este parseo.
   *
   * Si el formato cambiara, se devuelve un único elemento con `from: null`: el dato se
   * degrada, pero no se pierde el evento ni se rompe nada.
   */
  function incomingMessages(content: unknown): Array<{ from: string | null; chars: number }> {
    const text = contentToText(content);
    const marker = /^From "(.+?)":$/gm;
    const marks: Array<{ name: string; start: number; end: number }> = [];
    let match: RegExpExecArray | null;
    while ((match = marker.exec(text)) !== null) {
      marks.push({ name: match[1], start: match.index, end: marker.lastIndex });
    }
    if (marks.length === 0) return [{ from: null, chars: text.length }];
    return marks.map((mark, i) => ({
      from: mark.name,
      chars: (i + 1 < marks.length ? marks[i + 1].start : text.length) - mark.end,
    }));
  }

  // ── Eventos de pi ─────────────────────────────────────────────────────────

  pi.on("tool_execution_start", async (event) => {
    if (event.toolName !== "link_send") return;
    const args = (event.args ?? {}) as { to?: unknown; message?: unknown };
    pending.set(event.toolCallId, {
      to: String(args.to ?? ""),
      chars: String(args.message ?? "").length,
    });
  });

  pi.on("tool_execution_end", async (event) => {
    if (event.toolName !== "link_send") return;
    const call = pending.get(event.toolCallId);
    pending.delete(event.toolCallId);

    // link_send devuelve un resultado "correcto" con details.error cuando el destinatario no
    // existe o el hub no entregó, así que isError por sí solo no basta para decir que salió.
    const details = (event.result?.details ?? {}) as { to?: unknown; error?: unknown };
    const to = call?.to || String(details.to ?? "") || null;
    const failed = Boolean(event.isError) || Boolean(details.error);
    enqueue("link.message.sent", to, {
      chars: call?.chars ?? 0,
      ok: !failed,
      ...(failed && details.error ? { error: String(details.error) } : {}),
    });
  });

  pi.on("message_start", async (event) => {
    const message = event.message as any;
    if (message?.role !== "custom" || message.customType !== "link") return;
    const batch = incomingMessages(message.content);
    const batchId = batch.length > 1 ? randomUUID() : undefined;
    batch.forEach((item, index) => {
      enqueue("link.message.received", item.from, {
        chars: item.chars,
        ...(batchId ? { batch_id: batchId, batch_index: index, batch_count: batch.length } : {}),
      });
    });
  });

  pi.on("session_shutdown", async () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    pending.clear();
    await flush();
  });
}
