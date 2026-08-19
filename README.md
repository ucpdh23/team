# team-pi

Infraestructura Docker Compose que levanta un **equipo de 5 agentes [pi](https://pi.dev)**
(`@earendil-works/pi-coding-agent`), cada uno en su propio contenedor con su propio rol,
que se coordinan entre sí en tiempo real a través de **[pi-link](https://pi.dev/packages/pi-link)**.

## Objetivo

Simular un equipo de desarrollo software compuesto por agentes autónomos especializados:

| Rol | Contenedor | Responsabilidad |
|---|---|---|
| **manager** | `pi-manager` | Coordina al equipo, reparte y prioriza tareas, sintetiza resultados, punto de contacto con el humano al mando. |
| **backend** | `pi-backend` | Desarrollo del servicio/API backend (stack por decidir). |
| **frontend** | `pi-frontend` | Desarrollo de la interfaz de usuario (stack por decidir, previsiblemente Angular). |
| **devops** | `pi-devops` | Infraestructura, CI/CD, despliegue y observabilidad — incluida esta propia infraestructura. |
| **cypress** | `pi-cypress` | Pruebas end-to-end de backend + frontend. |

Cada agente tiene su propia configuración de plugins/paquetes de pi y su propio contexto de
equipo (`AGENTS.md`), y todos hablan entre sí por prompt vía pi-link, sin intervención
humana en el canal de comunicación.

## Arquitectura

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  pi-manager │     │  pi-backend │     │ pi-frontend │     │  pi-devops  │     │  pi-cypress │
│             │     │             │     │             │     │             │     │             │
│  pi + tmux  │     │  pi + tmux  │     │  pi + tmux  │     │  pi + tmux  │     │  pi + tmux  │
│  + broker   │     │  + broker   │     │  + broker   │     │  + broker   │     │  + broker   │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │                   │                   │
       └───────────────────┴─────────┬─────────┴───────────────────┴───────────────────┘
                                      │  red bridge normal de docker-compose
                                      │  (cada contenedor conserva su propia IP y puertos)
                                      ▼
                     volumen compartido "pi-link-coord" (elección de hub vía flock)
```

Cada contenedor es independiente a nivel de red — no hay ningún contenedor "especial" a
nivel de infraestructura. Los 3 componentes que corren dentro de cada uno:

- **`pi`** — el agente en sí, dentro de una sesión **tmux persistente** (sobrevive aunque
  nadie esté conectado; se autorrelanza si crashea).
- **`pi-link`** (extensión de pi) — el canal de comunicación entre agentes. Solo sabe hablar
  con `127.0.0.1:9900` (hardcoded, sin auth, solo loopback — ver
  [docs de pi-link](https://github.com/alvivar/pi-link)).
- **`pi-link-broker.sh`** — un script propio de este proyecto que resuelve el problema de
  que `pi-link` esté atado a loopback: hace posible que 5 contenedores de red independiente
  se descubran igualmente entre sí, con failover automático. Ver más abajo.

### Cómo se conectan los 5 agentes sin compartir red

`pi-link` usa una topología hub-spoke fija a `127.0.0.1:9900`: el primero en arrancar hace de
hub (WebSocket server) y el resto se conecta como cliente. Eso funciona out-of-the-box en una
sola máquina con varias terminales, pero no entre contenedores con IPs distintas — y el
puerto no es configurable ni por variable de entorno, ni por flag, ni por fichero de config.

En vez de fusionar la red de los 5 contenedores (lo que reventaría cualquier puerto propio
de cada stack — 8080, 4200, etc. — al compartirse entre los 5), cada contenedor lleva un
**broker** (`docker/pi-link-broker.sh`) que:

1. Compite por un **`flock`** exclusivo y no bloqueante sobre un fichero en el volumen
   compartido `pi-link-coord`. Quien lo consigue es el hub; el lock se libera solo (a nivel
   de kernel del host) si ese contenedor muere, así que el resto vuelve a competir por el
   rol automáticamente.
2. **El contenedor-hub** expone su `127.0.0.1:9900` (donde `pi-link` ha bindeado de verdad)
   hacia el resto de la red en un puerto propio de esta malla, `0.0.0.0:9901`, vía `socat`.
3. **El resto (spokes)** mantiene un relay `socat` local que reenvía su propio
   `127.0.0.1:9900` hacia `<hub>:9901`.

`pi-link` nunca sabe que nada de esto existe — solo ve su `127.0.0.1:9900` local funcionando
o no, y reacciona con su propia lógica de reconexión (backoff aleatorio de 2-5s). Si el
contenedor-hub cae, el resto se reconecta solo, siguiendo el procedimiento propio de
`pi-link`, sin que ningún script externo le mande nada directamente al proceso `pi`.

## Estructura de carpetas

```
.
├── docker-compose.yml
├── .env.example              # copia a .env — ANTHROPIC_API_KEY es opcional (ver Autenticación)
├── docker/
│   ├── Dockerfile.pi           # imagen base: manager, backend, frontend, devops
│   ├── Dockerfile.cypress      # variante sobre cypress/included (TODO: fijar versión)
│   ├── entrypoint.sh           # instala paquetes pi, arranca broker + sesión tmux, watchdogs
│   ├── pi-link-broker.sh       # elección de hub (flock) + relays socat (ver Arquitectura)
│   └── generate-tmux-conf.sh   # genera /etc/tmux.conf en build-time (colores + extended-keys)
├── agents/
│   └── <rol>/
│       ├── AGENTS.md           # contexto de equipo: quién es este agente, quiénes son los demás
│       └── extensions/         # extensiones locales de pi específicas de este rol
└── workspace/
    └── <rol>/                  # código fuente de ese rol, montado en /workspace del contenedor
```

`<rol>` es uno de: `manager`, `backend`, `frontend`, `devops`, `cypress`.

## Requisitos

- Docker y Docker Compose v2 (`docker compose ...`, no `docker-compose`).
- Una máquina con acceso a internet para el build (descarga la imagen base de Node/Cypress e
  instala `pi` y `pi-link` vía npm).

## Puesta en marcha

```bash
cp .env.example .env   # rellena ANTHROPIC_API_KEY si quieres, o déjalo vacío (ver abajo)
docker compose up -d --build
```

Para reconstruir tras cambiar cualquier Dockerfile/script y recoger los cambios sin perder
sesiones ni logins ya hechos:

```bash
docker compose up -d --build
```

> **No uses `docker compose down -v` / `--volumes`** salvo que quieras borrar a propósito
> los volúmenes con los logins y el estado de cada agente — no hay forma de deshacerlo.

## Autenticación

No hace falta `ANTHROPIC_API_KEY` para arrancar. Si lo dejas vacío en `.env`, la primera vez
que te conectes a la sesión de cada agente haces `/login` de forma interactiva y eliges el
proveedor que quieras; queda persistido en el volumen de ese agente (`/root/.pi/agent`), así
que solo hace falta una vez por contenedor.

## Conectarte a un agente

Cada agente corre en una sesión tmux persistente (sigue viva aunque nadie esté conectado):

```bash
docker exec -it pi-<rol> tmux attach -t pi
```

Para desconectarte **sin matar la sesión**: `Ctrl-b` seguido de `d` (el prefijo por defecto
de tmux — no lo hemos tocado). `Ctrl+D` dentro de `pi`, en cambio, hace que `pi` termine su
propia sesión (igual que en `bash` o un REPL de Python); como es el único proceso de esa
sesión tmux, se cierra con él, y el watchdog de `entrypoint.sh` la vuelve a levantar en
~5s — el contenedor Docker en sí nunca se reinicia, solo el proceso `pi` de dentro.

## VS Code remoto

No hace falta nada especial en las imágenes. Si el `docker compose` corre en una máquina
remota (p. ej. una EC2): conecta con **Remote-SSH** a esa máquina con tu acceso SSH normal
a la instancia, y una vez dentro de esa ventana remota usa la extensión **Dev Containers →
Attach to Running Container** — verá el Docker daemon local de esa máquina con normalidad.
Cada contenedor tiene un `container_name` fijo (`pi-manager`, `pi-backend`, ...) para
identificarlo fácilmente en la lista.

## Plugins/paquetes por agente

Cada servicio en `docker-compose.yml` tiene su propia variable `PI_PACKAGES` (paquetes pi
adicionales instalados vía `pi install npm:...` / `git:...`, separados por espacio) y su
propia carpeta `agents/<rol>/extensions/` (extensiones locales de proyecto). `pi-link` se
instala en los 5 por ser el mecanismo común de comunicación; el resto de plugins/skills de
cada rol se gestionan de forma independiente.

## Contexto de equipo (`AGENTS.md`)

`pi` carga automáticamente `AGENTS.md` desde el directorio de trabajo al arrancar. Cada rol
tiene el suyo en `agents/<rol>/AGENTS.md`, montado en `/workspace/AGENTS.md` de su
contenedor: explica el rol de ese agente, quiénes son el resto del equipo y cómo hablar con
ellos vía pi-link (`link_list`, `link_send`, `link_prompt`, `link_compact`). Al ser un bind
mount normal, si se edita desde dentro de la sesión el cambio se escribe directamente en el
repo — no hace falta hacer nada especial para persistirlo.

## Troubleshooting

**Caracteres especiales rotos (`_` en vez de tildes/¡¿/ñ)** — la imagen fija
`LANG=LC_ALL=C.UTF-8` en el Dockerfile; si lo ves después de un cambio de imagen, reconstruye
con `docker compose up -d --build`.

**Colores/grises que se ven negros dentro de tmux** — `docker/generate-tmux-conf.sh` genera
`/etc/tmux.conf` en build-time con `default-terminal tmux-256color` + `terminal-overrides
",*:RGB"` para negociar truecolor correctamente. Si persiste, es probable que el terminal
*cliente* desde el que haces `docker exec ... tmux attach` no esté anunciando soporte
truecolor.

**Un agente no aparece conectado a pi-link / `link_list` no lo ve** — comprueba en orden:

```bash
docker logs pi-<rol> --tail 20                       # ¿arrancó el broker? ¿es hub o spoke?
docker exec pi-<rol> cat /var/run/pi-link/hub.addr    # ¿a quién apunta la malla ahora mismo?
docker exec pi-<rol> tmux capture-pane -t pi -p       # estado de pi-link visible en pantalla
```

## Pendiente / TODO

- **Stack tecnológico por rol** (backend Java/Python, frontend Angular, devops
  terraform/kubectl...) — cuando se decida, `Dockerfile.pi` se dividirá en uno por rol con
  el toolchain correspondiente (marcado con `TODO` en el propio fichero).
- **Extensión pi de Eclipse headless** para gestión de código Java, pendiente de integrar
  cuando se confirme el stack de backend.
- **Versión de `cypress/included`** — `Dockerfile.cypress` usa `latest` como placeholder,
  hay que fijarla a la versión de Cypress real del proyecto.

## Licencia

Pendiente de definir.
