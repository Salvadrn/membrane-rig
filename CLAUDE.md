# membrane-rig — cerebro compartido de todos los agentes

Sistema de control en **Raspberry Pi** que automatiza el banco de permeabilidad de
membranas del laboratorio **TEMP / ENLACE** de UC San Diego (grupo del Prof.
Renkun Chen). Reemplaza las dos fuentes de error humano del procedimiento manual
—sostener la presión a mano y cronometrar la colecta moviendo la manguera— por un
lazo cerrado a 20 Hz y un diverter de solenoide.

Mide pares (ΔP, Q) y deriva la permeabilidad de Darcy por el **método de la
pendiente**: `k = b_Pa · μ · L / A`, poro `d = √(32k)`, con `R² ≥ 0.98` como
criterio de que la muestra sigue la ley de Darcy.

Dueño: **Salvador Adrián Martínez García**. Repo privado
`github.com/Salvadrn/membrane-rig`.

## Estado real del proyecto (no lo contradigas)

- El software corre **completo en simulación** (`mode: sim`) y está verificado de
  punta a punta: playlist, análisis, gráfica, Excel.
- **Puesta en marcha en hardware avanzando (2026-08-06). El rig MIDIÓ PRESIÓN** por
  el camino de software completo (`Config → build_hal → Ads1115Sensor` reales, no un
  script auxiliar): commit `57c8ec4` (`i2cdetect` → `0x48`) y **`b37d2a2`** (presión).
  Tres ciclos a soplido: picos **10.83 / 11.05 / 10.17 kPa**, regresos a
  **−0.04 / −0.04 / −0.05** — el regreso repetible al mismo cero es lo que lo vuelve
  **medición**, no lectura (sin deriva ni histéresis visible; CSV+PNG en `runs/`).
- **Calibración de ESTE banco, medida y no asumida (`config.yaml`):** `divider_ratio`
  **= 0.7346** (verde 0.500 V con multímetro → A0 0.3673 V), cero **0.01 kPa**, ruido
  de fondo **±0.04 kPa** p-p **con el servo desconectado** (era ~1 parte en 1000 vs
  35 kPa). ⚠ Con el servo conectado subió a **~0.35 kPa p-p** (acoplamiento eléctrico, no
  pigpio). **Su impacto en k está SIN RESOLVER, y no es cuestión de tamaño** (análisis
  de Datos): el punto de la regresión es la **media de ~1200 muestras**. Si el ruido es
  **aleatorio**, impacto en k = **0.0000 %** (se promedia). Si el acoplamiento **escala
  con el duty del PWM** (el servo trabaja 6× más a 60 que a 20 kPa), es un **sesgo de
  −0.72 % que R² NO ve** (se queda en 0.99999) — sería la única fuente que sesga k.
  **La evidencia ya existente inclina hacia el aleatorio/benigno:** las 3 tomas de
  Hardware (demonio corriendo/detenido/rearrancado = 0.343 / 0.361 / 0.418 p-p) NO
  bajan con el PWM detenido → la conmutación no es la fuente dominante, así que
  difícilmente escala con el duty (Caso B se apoyaba en eso). Queda como sospecha la
  corriente de reposo del servo, que podría crecer con carga. Lo confirma una prueba
  barata (cero a varios comandos de válvula): en seco a atmósfera da un **"sí"
  definitivo** pero un **"no" solo provisional** (falta la componente de carga
  mecánica); Datos la pidió a Hardware. Y **el sim NO puede detectar el caso sesgado**:
  `MockPlant` usa
  `random.gauss` independiente, solo produce el aleatorio — hay que modelarlo antes de
  confiar en cualquier validación de exactitud de k. El "1 parte en 1000" ya no aplica. Ese 0.7346
  contra el nominal 0.6875 es **6.8 %** — con el nominal el rig reportaba **+7 kPa a presión
  cero**. La procedencia está en el comentario de `config.yaml`: **no lo "corrijas" de
  vuelta a 0.6875** viendo resistencias marcadas 10k/22k; el medido manda.
- **Lo que SIGUE sin existir (no lo contradigas):** **no hay ningún `k` medido, ni
  un par (ΔP, Q).** La válvula de aire (servo) YA se mueve y calibró, pero
  **presurizar está BLOQUEADO por DOS cosas**, no una: (a) **Stage 8.3** —medir y
  fijar el regulador de aire, que con el alivio EN LA MANO pero SIN MONTAR es el
  **único backstop**— sigue en `unknown`; y (b) los **chequeos en frío del Stage 0
  NUNCA se corrieron** (ninguno; la causa del corto de la Pi 1 sigue abierta). El
  **riel de 12 V nunca se energizó**, así que el **diverter jamás ha operado** (y le
  falta el conmutador MOSFET/relevador y el 1N5819 montado). Lo que protegió al
  proyecto hasta hoy es que **nada tocó el 12 V**: sensado a 3.3 V, transductor y
  servo a 5 V. Todo resultado **publicado** (paper, charla) sigue siendo de simulación.
- **Servo — PORT A PWM DEL KERNEL HECHO, acoplado y calibrado (2026-08-07).** El
  bloqueo de Trixie (pigpio no existe; `ServoValve` lanzaba al importarlo y tumbaba
  toda la app porque `build_hal` construye la válvula antes que el sensor) se resolvió
  primero con `valve.type: "none"` (`NoOpValve`, para leer sensores) y ahora con el
  driver real **`servo_kpwm`** (`src/hal/servo_kpwm_valve.py`, `ServoKernelPwmValve`):
  usa el **PWM por hardware del kernel** en GPIO18, no pigpio ni el software-PWM de
  lgpio. Calibrado por Adrián en la manija, **acoplado**: `0% = 260° = CERRADO
  (1759 µs, estado seguro)`, `100% = 170° = ABIERTO (1093 µs)`, **`invert: true`** — la
  dirección viene de SU medición, no de inferencia (el recorrido da 90°, el cuarto de
  vuelta de una bola, y se auto-valida). **UBEC FUERA:** dejó de entregar la noche del
  2026-08-06 y se sacó de la línea; el servo ahora corre del **5 V del Pi (pin 2)**,
  retorno **pin 20**, con cap ≥1000 µF pegado al servo (`docs/wiring_sin_ubec.md`,
  `6965275`). Pendiente antes de presión: pasada formal de `valve_check` (los 3 pasos);
  `servo_close_us` sigue en `0` (cierre a fondo sin calibrar); y **hacia dónde deriva
  al cortar energía sin medir** (COMMISSIONING 10.7). `config.py` valida
  `("servo","pwm","servo_kpwm","none")`.
- **Principio (de ese arreglo, no lo violes) — tiene DOS mitades, ambas obligatorias:**
  1. Un actuador ausente es **opt-in, nunca fallback automático**. `build_hal` NO
     captura el fallo del servo para sustituirlo solo: un rig que arranca callado sin
     control de presión —mientras el operador cree que el software aún puede cerrar la
     válvula— es **peor** que uno que se niega a arrancar. Un actuador ausente es una
     **decisión, no un accidente**.
  2. Pero **nada del actuador puede impedir leer el sensor — ni en `build_hal` ni en
     la validación de config.** Rechazar `none`+setpoints en carga volvería a poner el
     actuador en el camino del sensor (el mismo bug, otra capa) y bloquearía el
     bring-up. Una corrida sin actuador **falla honestamente en runtime**: el watchdog
     de planta dice *"plant unresponsive"*, que es literalmente lo que pasa.
  No agrega peligro: `to_safe()` es no-op, pero tampoco hay nada que pueda ABRIR la
  válvula → no puede producir presión; la red de siempre sigue siendo la única: la
  válvula del panel se cierra a mano.
- **Acceso remoto:** el directo (SSH por cable / misma red) **no funciona** — UCSD
  aísla clientes en `UCSD-Conferences`. El canal de trabajo es la **consola de Pi
  Connect** (alguien pega comandos). El túnel de Cloudflare (para la UI web) sigue
  pendiente; Cloudflare sí es alcanzable desde esa red, así que el túnel es viable
  cuando se monte.
- **Todos los números PUBLICADOS siguen siendo de simulación.** El paper lo declara
  explícitamente. No presentes resultados de sim como si fueran del rig físico —
  y no presentes el `0x48` como una medición de permeabilidad: dice que el chip
  responde, nada más.

## Sistema de agentes (multi-sesión)

Este repo se trabaja con 6 sesiones de Claude Code. **Si eres una sesión nueva:
lee tu rol completo en `.claude/roles/<tu-agente>.md` antes de tocar nada.**

| Agente | Área |
|---|---|
| **General** | Coordinación, provisión de la Pi, despliegue, decisiones cross, mantener este archivo y los roles |
| **Control** | `src/app.py`, `src/control/`, `sequencer.py`, `safety.py`, `playlist.py`, `config.py` |
| **Hardware** | `src/hal/`, `BOM.*`, `docs/ASSEMBLY.md`, cableado, calibración, puesta en marcha |
| **Datos** | `analysis.py`, `plotting.py`, `export_excel.py`, `logging_csv.py`, sims de validación |
| **Interfaz** | `src/ui/web.py`, `src/ui/cli.py`, apps de Mac |
| **Paper** | `docs/paper/`, `README.md`, entregables de laboratorio |

**Todos trabajan en el checkout principal** `~/Desktop/membrane-rig` (sin
worktrees: las áreas son disjuntas y el `.venv` vive aquí). Antes de tocar algo:
`git pull`. Al terminar: `commit` + `push`.

Para pasar trabajo entre sesiones, usa la herramienta de mensajes entre sesiones
(`send_message`) — llega como turno de usuario en la sesión destino.

## Reglas de oro (para TODOS los agentes)

- **Git a nombre de Adrián.** Cada cambio se commitea y pushea sin preguntar,
  autor `Salvadrn <adrngeng@gmail.com>`. **Nunca** co-autoría de Claude.
- **Checkout compartido: commitea POR RUTA, nunca por index.** Seis sesiones
  escriben sobre `~/Desktop/membrane-rig` al mismo tiempo, así que el index es
  territorio común y `git add X && git commit` se lleva **todo lo que otra sesión
  dejó preparado**. Pasó de verdad: el commit `4c7687e` ("stop promising a relief
  valve") arrastró tres archivos de `src/` de Datos, cuyo commit había fallado
  dejándolos en el index — el historial ahora atribuye el error estándar de `k` a
  un commit sobre válvulas de alivio. Usa siempre la forma con rutas
  (`git commit CLAUDE.md -m "…"`), **nunca `-a` ni el index completo**, y corre
  `git status` antes de commitear. Con **archivos nuevos** esa forma falla
  (`pathspec did not match`) porque git aún no los conoce: hay que
  `git add <rutas>` primero y luego commitear **con esas mismas rutas** — el
  `git add` es lo de menos, lo que acota el commit es la lista de rutas del
  `git commit`. No caigas en `git add -A` para salir del paso, que es
  exactamente lo que esta regla evita. Lo que vuelve esto difícil de detectar: por la
  regla de arriba **todas las sesiones firmamos igual**, así que el autor no
  distingue a nadie — para saber quién hizo qué hay que mirar los archivos
  tocados, no el `Author`. Si ya
  se pusheó, **no se reescribe historia**: todos trabajan sobre main; se anota y
  se sigue.
- **La seguridad de presión no se negocia.** El rig presuriza una celda con una
  malla delicada. La escalera es:

  | Capa | Presión | Acción |
  |---|---|---|
  | Pruebas normales | ≤ 60 kPa | — |
  | Límite del espécimen | 65 kPa (editable) | No se puede ni encolar más |
  | Techo por corrida | min(max(setpoint) + 10 kPa, límite del espécimen) | Detiene en seguro + alarma (reintenta/para) |
  | Corte global | 80 kPa | Aborta |
  | Alivio mecánico | ~90 kPa | Pedido de nuevo (2026-07-31) — aún sin instalar |
  | Saturación del sensor | 103 kPa | — |

  Nadie afloja estos límites sin decírselo a Adrián. La UI solo puede apretar.

  **Historia del alivio:** Adrián lo sacó del pedido el 2026-07-29 ("es muy poca
  presión") y lo **reinstauró el 2026-07-31** al preparar la operación remota — el
  correo a Roxanne ya pide confirmar su estatus. Hasta que la pieza llegue y esté
  montada y tarada, la fila de arriba es un plan, no una protección: **hoy nada
  actúa sin software y sin energía**, y cerrar el suministro a mano al terminar
  sigue siendo obligatorio. La tarada del regulador de aire sigue sin
  documentarse y sigue gateando cinco decisiones.
  - **Vocabulario — "ventear" está reservado.** Solo el **alivio mecánico** ventea
    (libera presión por un camino de escape). El software **cierra la alimentación**;
    la presión baja por **permeación** a través de la membrana (~20 s), o —con una
    malla tapada o muy fina— **no baja**. No escribas que el software o un aborto
    "ventea/vents": describe lo que pasa (cierra el aire; el vaso decae por
    permeación, o no). Decidido con Paper el 2026-08-06 tras encontrarlo en 5+
    lugares que prometían un mecanismo y una velocidad inexistentes.
- **Verificar antes de decir "listo".** Corre el sim, corre el test, mira la
  salida. Nada de "debería funcionar".
- **Al cambiar una constante, un COMPORTAMIENTO o una DECISIÓN, barre lo
  DERIVADO.** Un find/replace del literal no basta. Tres clases, y solo la
  primera se caza con grep:
  - **Cifras** calculadas con el valor viejo, sin el número ni el nombre de la
    pieza. Caso real (divisor 10k/20k → 10k/22k): el paper traía `1.366 V` que
    era `2.047 × 0.667` y no contenía "0.667" ni "20k".
  - **Afirmaciones** que dependían del hecho viejo. Caso real (etapa 2 + clamp):
    cinco documentos decían *"una prueba de 20 kPa aborta cerca de 30"*. No
    cambió ningún número: cambió lo que el sistema HACE.
  - **Recomendaciones** que solo tenían sentido con la pieza vieja. Caso real
    (alivio fuera del pedido): `docs/wiring_fluidos.html` advertía que la tee
    Swagelok quedaba corta *"porque el alivio y el transductor son dos tomas"* —
    sin alivio hay una sola, y la advertencia se invirtió en un consejo de
    comprar un fitting para una pieza que nunca va a llegar. **Ese derivado
    cuesta dinero.**

  Las cifras se cazan preguntando *"¿qué se calculó con el viejo?"*. Las otras dos
  **no se cazan con grep** — hay que releer lo que cada documento *afirma* y
  *recomienda*, contra el código y contra las decisiones vigentes. Si cambiaste
  **qué hace** el sistema o **qué se va a comprar**, abre `CLAUDE.md`,
  `README.md`, `.claude/roles/*`, `docs/` y `docs/paper/` y léelos.
- **Un barrido solo limpia lo que existía cuando corrió.** La regla de arriba
  ataca lo viejo que quedó; su gemela es **texto nuevo escrito desde un modelo
  mental viejo**, que reintroduce el error sin que ningún barrido lo cache — la
  sección no estaba cuando se barrió, y releer lo cambiado no la encuentra. Caso
  real (2026-07-31): el barrido `16d88ac` sacó del repo entero la afirmación de
  que el alivio mecánico protege sin software; una sección de `REMOTE_ACCESS.md`
  redactada DESPUÉS la reintrodujo textual — una afirmación de seguridad, la peor
  categoría para reintroducir. Si escribes una sección nueva sobre un tema
  corregido hace poco, verifícala contra el estado actual, no contra lo que
  recordabas — sobre todo si empezaste a redactarla antes de la corrección.
- **Simulación ≠ hardware.** Cualquier afirmación sobre el comportamiento físico
  va marcada como pendiente de validar en el rig.
- **Un sensor caído nunca se interpreta como "presión baja"** — se trata como
  falla de instrumento y se ventea. Ver `src/safety.py`.
- **Idioma:** código y comentarios en inglés; documentos de laboratorio en
  inglés; conversación con Adrián en español mexicano.
- **Lo que no se versiona:** `.venv/`, `runs/run_*`, `runs/playlist_*`,
  `playlist.json`, `runs/server.log`, archivos de bloqueo de Word (`~$*`).

## Cómo se corre

```bash
# simulación en la Mac (o doble clic en "Membrane Rig.app" del Escritorio)
./.venv/bin/python run.py web --sim          # http://localhost:8000

# en la Raspberry Pi, con hardware
bash /boot/firmware/membrane-rig-setup.sh    # extrae el repo y corre install.sh
```

## Contexto de laboratorio

- Mentor: **Kwangsoo Cho** `kwcho@ucsd.edu`. PI: **Prof. Renkun Chen**
  `rkchen@ucsd.edu`. Compras: **Roxanne Vanderheiden** (`rvanderh@ucsd.edu` /
  `rvanderheiden@ucsd.edu`). Compañero ENLACE: Rodrigo Nicolle.
- Las compras pasan por Kwangsoo → Roxanne. Los Excel se comparten como link de
  SharePoint del Tec, no como adjunto.
