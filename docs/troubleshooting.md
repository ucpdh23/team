# Troubleshooting

Common problems. Index: [README](../README.md#troubleshooting).

## Troubleshooting

**Build fails on Windows with `/usr/bin/env: 'bash\r': No such file or directory`** — Git for
Windows with its default `core.autocrlf=true` converted this repo's shell scripts to CRLF on
checkout, so the shebang line became `#!/usr/bin/env bash\r` and the container looked for an
interpreter literally called `bash\r`. The repo's `.gitattributes` (`* text=auto eol=lf`)
prevents it for any fresh clone, and every Dockerfile strips CRs from the scripts it copies
before running them, so a build works either way. If you cloned **before** `.gitattributes`
existed, your working tree still holds the converted files — renormalize it once:

```bash
git add --renormalize .
git checkout -- .
```

(`git status` should then show nothing; if it lists the `.sh` files, commit that renormalization
or reset it, whichever fits.) A fresh `git clone` also does the job.

**Broken special characters (`_` instead of accents/¡¿/ñ)** — the image sets
`LANG=LC_ALL=C.UTF-8` in the Dockerfile; if you see this after an image change, rebuild with
`python setup.py --start`.

**Colors/grays showing up as black inside tmux** — `docker/generate-tmux-conf.sh` generates
`/etc/tmux.conf` at build time with `default-terminal tmux-256color` + `terminal-overrides
",*:RGB"` to negotiate truecolor correctly. If it persists, the *client* terminal you're
running `python setup.py --tmux <role>` from is likely not advertising truecolor support.

**Mouse wheel scrolling in tmux** — `/etc/tmux.conf` also sets `mouse on`, so scrolling up
with the wheel enters tmux's copy-mode automatically and scrolls the pane's history;
scrolling back down to the bottom exits copy-mode on its own, no `Ctrl-b [`/`q` needed.
Trade-off: selecting text with the mouse to copy it now needs **Shift+drag** in most
terminal emulators instead of a plain drag, since tmux itself intercepts plain mouse clicks
for its own use (pane focus, drag-to-resize, etc.) once mouse mode is on.

**An agent doesn't show up on pi-link / `link_list` doesn't see it** — check in order:

```bash
python setup.py --logs <role>                          # did the broker start? hub or spoke?
docker exec pi-<role> cat /var/run/pi-link/hub.addr     # who is the mesh pointing at right now?
docker exec pi-<role> tmux capture-pane -t pi -p        # pi-link's on-screen status
```

(the last two are quick one-off commands, not worth a dedicated `setup.py` flag — or run
`python setup.py --bash <role>` and type them directly inside the container.)

**The console's Sistema tab shows only the console itself** — it lists the containers of its
own Compose project (label `com.docker.compose.project`) plus any whose name starts with
`CONTAINER_PREFIX`. If your agents were created from a *different checkout* — another
directory is another Compose project — or before you changed `CONTAINER_PREFIX`, they fall
outside both. The tab says so, naming its own project and the other ones it can see on the
same daemon. Compare:

```bash
docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}'
curl -s localhost:4070/api/health          # fields: project, prefix, containers
```

The fix is usually to work from a single checkout: bring the branch there and run
`python setup.py --start`, which creates all six containers in the same project.

**`ports are not available: ... bind: address already in use` on 4070** — something else is
already publishing that port, most often a console from *another* checkout of this project
(with Docker Desktop + WSL2 the daemon and `localhost` are shared). Find it and either stop it
or give this cluster its own port:

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 4070
echo "CONSOLE_PORT=4071" >> .env && python setup.py --start
```

**The console is up but the graph in Actividad stays empty** — the agents report what they
send through the extension mounted at `agents/_shared/pi/extensions/team-console`, which only
exists in containers created *after* that mount was added. Recreate them
(`python setup.py --start`) and check that one of them sees it:

```bash
docker exec pi-manager ls /root/.pi/agent/extensions/team-console
docker exec pi-manager printenv CONSOLE_URL
```
