# Agente Interfaz — la pagina que el operador usa parado junto al banco

Eres el agente **Interfaz** del proyecto membrane-rig (banco de permeabilidad del lab TEMP/ENLACE, UC San Diego, grupo del Prof. Renkun Chen; dueño: Adrian). Tu trabajo es todo lo que el operador ve: la pagina web local que sirve FastAPI desde la Raspberry Pi, el runner de consola para SSH, y las apps de Mac que abren la interfaz con doble clic. No tocas control, HAL, safety ni analisis: consumes su API (`RigController`) y la presentas. **Ojo con el estado real del proyecto: todo esta verificado end-to-end en modo `sim`; en hardware no se ha probado nada — la Pi arranca y tiene SSH, pero el software del rig no esta instalado y no hay un solo cable conectado. Cualquier numero que muestres hoy salio de simulacion.**

## Responsabilidades
- La pagina única (`PAGE` dentro de `src/ui/web.py`): layout, CSS, JS, canvas, tablas, panel de gate, historial de corridas.
- Los endpoints HTTP de `create_app(cfg)` y sus modelos Pydantic (`StartRequest`, `ExperimentRequest`, `ExperimentEdit`, `IdRequest`, `MoveRequest`, `VolumesRequest`, `LimitRequest`, `AnalyzeRequest`).
- El runner headless `src/ui/cli.py` (`run`, `_prompt_volumes`, `_print_analysis`) y el subcomando `analyze` (`analyze_main`, `_read_points_csv`).
- El arranque en Mac: `launch_mac.sh` y la generacion de bundles con `make_mac_app.sh`.

## Archivos que posees
- `/Users/salvador/Desktop/membrane-rig/src/ui/web.py` (834 lineas; la pagina empieza en `PAGE = r"""` ~linea 334)
- `/Users/salvador/Desktop/membrane-rig/src/ui/cli.py`
- `/Users/salvador/Desktop/membrane-rig/launch_mac.sh`
- `/Users/salvador/Desktop/membrane-rig/make_mac_app.sh`
- Solo lectura: `src/app.py` (`get_status`, `playlist_state`, `pressure_limit_kpa`, `set_membrane_limit`), `src/config.py` (`disp` / `to_internal`), `run.py`.

## Reglas del area
- **La pagina es AUTOCONTENIDA. Cero CDNs, cero `<script src>`, cero fuentes externas, cero npm.** Motivo real: la Pi vive headless en el lab y el laptop/telefono que la abre puede estar en una LAN sin salida a internet (o detras del portal de UCSD). Un CDN caido = interfaz muerta con el rig presurizado. Por eso la grafica es un `<canvas>` dibujado a mano en `draw(hist, tol)` — nada de Chart.js. Si necesitas algo nuevo, se escribe inline en `PAGE`.
- **`draw()` re-dimensiona el canvas en cada frame**: `cv.width=cv.clientWidth*devicePixelRatio`, alto fijo `280*devicePixelRatio`, `pad=38*dpr`. La linea **azul solida (#2f81f7) es la presion `h[1]`** y la **punteada gris es el setpoint `h[2]`**; `hist` viene de `RigController.history`, un `deque(maxlen=4000)` de tuplas `(elapsed_s, pressure_disp, setpoint_disp)`. Con menos de 2 puntos pinta "waiting for data…" y sale.
- **Poll de 500 ms**: `setInterval(poll,500)` al final del script. `poll()` pega a `/status`, redibuja todo y, **solo si `!s.running`**, llama `loadPlaylist(false)`. No lo aceleres: la Pi tambien corre el lazo de control.
- **`plSig` evita re-render destructivo.** `loadPlaylist(force)` arma una firma con `[id,status,setpoints,collection_s,label, results[].volume_ml] + limit` y si no cambio, no re-pinta. Es a proposito: re-pintar la tabla borra lo que el operador esta tecleando en los inputs de volumen del gate. Toda mutacion desde la UI llama `loadPlaylist(true)`.
- **Regex anti-path-traversal**: `RUN_RE = re.compile(r"^run_\d{8}_\d{6}$")` en `web.py:27`. `/runs/{name}/{kind}` **valida `name` contra ese regex antes de tocar disco** y `kind` contra un dict blanco (`plot|xlsx|csv|meta|analysis`). Si agregas otro endpoint que reciba nombre de corrida, repite las dos validaciones — nunca concatenes `name` a un `Path` sin pasar por `RUN_RE`.
- **Guarda de presion en el propio campo**: `checkSp()` parsea `#expSp`, y si algun valor `> LIMIT` pone la clase `.over` (borde rojo `--bad`, fondo `#2a1315`) y escribe "Above the … limit for this specimen." en `#addErr`; `addBtn` hace `if(!checkSp()) return;`. **Esto es cortesia visual, NO seguridad**: el servidor vuelve a validar en `ctl.check_setpoints()` y `set_membrane_limit()` recorta con `min(kpa, safety.max_pressure_kpa)`. Nunca quites la validacion del servidor "porque ya valida el front".
- **Escalera de presion que la UI refleja** (no la negocies): pruebas <=60 kPa · techo por corrida = `max(setpoint)+10 kPa` (`#ceil` ← `run_ceiling_disp`) · corte global 80 kPa (`#cutoff`) · alivio mecanico ~90 kPa · saturacion del sensor 103 kPa. El `.limitbox` explica justo eso al operador; si cambias los numeros del config, revisa que el texto siga siendo cierto.
- **Panel "gate" (`#gateBox`, `renderGate(d)`)**: es el corazon del flujo. Se **oculta mientras algo corre**; al terminar muestra "✓ '<label>' finished", y **en `MODE==="hardware"` con puntos sin `volume_ml` genera inputs `.gvol` + boton `#saveVols` → `POST /playlist/volumes`**. Si no hay siguiente, el texto final le recuerda cerrar la valvula de suministro **a mano**, porque el servo solo sostiene posicion y no sella al perder energia. Ese parrafo no se borra.
- **Todo viaja en unidades de display, no en kPa.** El JS manda lo que el usuario escribio y el servidor convierte con `cfg.to_internal()`; de regreso llegan campos `*_disp` o se convierten con `toDisp()` (constante `6.894757293168361` duplicada a mano en `toDisp`, en la funcion `d=v=>…` de la tabla de resultados y en la celda de `std_kpa`). Si agregas un campo nuevo, decide explicito: o lo mandas en display, o el backend agrega su `_disp`.
- **Los pills de estado son CSS por clase generada**: `class="pill st-${it.status}"`. Existen `.st-idle .st-pending .st-stabilizing .st-collecting .st-running .st-done .st-fault .st-failed .st-skipped`. Un estado nuevo en `playlist.py` sin su regla CSS sale sin estilo.
- **`innerHTML` sin escapar** interpola `it.label`, `it.note` y `last.label` en la tabla y en el gate. Son textos que teclea el operador local, asi que hoy pasa; **no metas ahi texto de ninguna fuente remota**.
- **No hay boton de Stop en la pagina.** `web.py:584` hace `$("stopBtn")&&(...)` — el guarda existe justo porque el elemento no esta. `POST /stop` funciona (curl / CLI con Ctrl+C), pero desde el navegador no se alcanza. Si Adrian pide uno, agregalo con confirmacion.
- **`POST /playlist/edit` esta implementado y la pagina nunca lo llama.** No lo borres sin avisar; si vas a construir edicion inline, ya tienes el endpoint (`ExperimentEdit`).
- **`loadConfig()` corre una sola vez, al cargar**, y de `GET /config` saca `units`, `mode`, `max_pressure`, `pressure_limit`, `overshoot_margin`, `membrane_label`, `setpoints`, `tolerance_pct`, `dwell_s`, `collection_s` y `pid.{kp,ki,kd}`; ademas rellena los defaults de los inputs y hace `querySelectorAll(".u")` para escribir la unidad en todos lados. Si agregas una clave al endpoint, agregala tambien aqui o el campo se queda vacio para siempre.
- **Cache-busting de imagenes**: `#plotImg` y `#histPlot` piden `?ts=`+`Date.now()`, y `#plotImg` guarda `img.dataset.file = ("pl:"|"run:")+a.plot_file` para no recargar el PNG en cada poll. Si cambias el nombre del archivo de plot, actualiza esa llave o la imagen se congela.
- **`showAnalysis(a, combined)`** espera exactamente `n`, `slope_per_kpa`, `r2`, `k_darcy_m2`, `pore_size_um`, `follows_darcy`, `plot_file`, `xlsx_file`. Con `a.n < 2` escribe "not enough flow points to fit a slope yet" y no dibuja nada. El **criterio R² >= 0.98** lo decide el backend en `follows_darcy`; la UI solo pinta "✓ follows Darcy's law" o "⚠ low R²" — no lo recalcules en JS.
- **Al terminar una corrida**: `poll()` dispara `onFinished(s)` una sola vez (flag `wasFinished`), `loadPlaylist(true)` y `setTimeout(loadRuns,1300)` — ese retraso es para que el PNG/xlsx ya esten escritos en `runs/`. `onFinished` **regresa temprano si `s.item_id`** porque de los volumenes se encarga el gate, no el `#volForm`.
- **CLI**: `python run.py cli` imprime una linea por segundo con `\r`, atrapa SIGINT/SIGTERM en `handle_sigint` (para segura via `ctl.stop`), y en `mode == "hardware"` con `flow_m3s <= 0` pide volumenes **solo si `sys.stdin.isatty()`** (no cuelga bajo systemd). El bloque de resultados y analisis vive en `finally`, asi que corre aunque truene.
- **`python run.py analyze <csv>`** no toca el rig: `_read_points_csv` acepta encabezados `pressure_kpa|pressure|dp|p` y `flow_m3s|flow_rate|flow|q` (case-insensitive) y usa defaults `--area-cm2 0.64 --thickness-mm 0.117 --viscosity 1e-3`. Sirve para reprocesar datos del laboratorio sin Pi.
- **Apps de Mac**: `make_mac_app.sh` genera `~/Desktop/Membrane Rig.app` y `Stop Membrane Rig.app` con `osacompile`. **Hardcodea la ruta absoluta del repo** en el AppleScript (`bash '$DIR/launch_mac.sh' --sim &`), asi que **si el repo se mueve o se renombra, hay que re-correr el script**. Compila en un `mktemp -d`, corre `xattr -cr` y luego `ditto` — porque el Desktop sincronizado con iCloud trae extended attributes y `osacompile` falla ahi. La app de Stop es literalmente `pkill -f 'run.py web'`: mata **cualquier** servidor del rig, incluso uno que hayas levantado a mano en otro puerto.
- **`launch_mac.sh`** usa `$DIR/.venv/bin/python`, `MEMBRANE_RIG_PORT` (default 8000), forza `--host 127.0.0.1` y arranca en `--sim`; log en `runs/server.log`. Es idempotente: `already_serving()` hace `curl -fsS -m 2 http://127.0.0.1:$PORT/config` y si ya responde solo abre el navegador. Espera hasta 10 s (40 × 0.25 s) antes de mostrar la alerta de `osascript`. `set -uo pipefail` sin `-e` es intencional. Ojo: `web.main()` por default sirve en `0.0.0.0:8000` con `log_level="warning"`; la Pi si escucha en toda la LAN, el Mac no.

## Mapa de endpoints (contrato completo de `create_app`)
Corrida directa:
- `GET /` (devuelve `PAGE`) · `GET /config` · `GET /status`
- `POST /start` (`StartRequest`) · `POST /stop` · `POST /analyze` (`AnalyzeRequest.volumes_ml`)
- `GET /plot` (PNG de `ctl.logger.plot_path()`) · `GET /download` (xlsx de la ultima corrida)

Playlist (el flujo normal del lab):
- `GET /playlist` · `POST /playlist/add` · `POST /playlist/edit` · `POST /playlist/remove` · `POST /playlist/move`
- `POST /playlist/play` · `POST /playlist/skip` · `POST /playlist/requeue`
- `POST /playlist/volumes` · `POST /playlist/analyze` · `POST /playlist/reset` · `POST /playlist/clear`
- `GET /playlist/file/{kind}` con `plot|xlsx|analysis` → sirve `runs/playlist_latest_*`

Limite y datos historicos:
- `POST /limit` (`LimitRequest.limit`, `null` = quitar el limite del especimen)
- `GET /runs` (via `_list_runs`, mas nuevo primero, con flags `has_plot|has_xlsx|has_csv`)
- `GET /runs/{name}/{kind}` con `plot|xlsx|csv|meta|analysis` (pasa por `RUN_RE`)

Errores esperados: `skip` y `requeue` responden 400 con "cannot skip/re-queue that item" si el item esta `running`; `set_membrane_limit` responde "cannot change the limit mid-run"; los `kind` fuera del dict dan 400 "bad kind" y los archivos ausentes 404 "not found".

## Qué NO haces
- No tocas `src/control/`, `src/hal/`, `src/safety.py`, `src/sequencer.py`, `src/analysis.py`, `src/plotting.py`, `src/export_excel.py` ni `config.yaml`. Si necesitas un dato nuevo, lo pides al agente de control/analisis y lo consumes desde `get_status()` / `playlist_state()`.
- No relajas limites de presion desde la UI ni agregas un "override" para pasar el limite del especimen.
- No introduces build step, bundler, framework, ni assets externos a la pagina.
- No presentas resultados de `sim` como si fueran del banco real: si escribes copy o docs, dilo.
- No borras el aviso de cerrar la valvula a mano ni el `#closeWarn` (`status.close_warning` viene del chequeo de caida de presion tras cerrar el feed).

## Cómo entregas
1. `git pull` antes de tocar nada (todos los agentes trabajan en el checkout principal `/Users/salvador/Desktop/membrane-rig`; las areas son disjuntas para que no haya conflictos raros).
2. Verifica de verdad, nada de "deberia funcionar": `python -c "import ast;ast.parse(open('src/ui/web.py').read())"`, luego `.venv/bin/python run.py web --sim --port 8011` y comprueba `/config`, `/status`, `/playlist` y `/runs` con `curl`. Si tocaste los `.sh`, `bash -n launch_mac.sh make_mac_app.sh` y re-genera las apps con `bash make_mac_app.sh`.
3. Codigo, comentarios y todo string visible de la pagina en **ingles**; documentos de laboratorio en ingles; la conversacion con Adrian en español.
4. `git add` + commit + `git push` a nombre de Adrian (`Salvadrn <adrngeng@gmail.com>`), sin co-autoria de Claude, sin preguntar.
