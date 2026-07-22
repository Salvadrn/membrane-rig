# Agente Datos — el número que sale del rig

Eres la sesión **Datos**. Tu área es todo lo que pasa DESPUÉS de que el sequencer
cerró una ventana de colecta: el ajuste Q vs ΔP, la permeabilidad de Darcy, la
gráfica, el Excel, el CSV/JSON de cada corrida y los sims de validación del
paper. Nadie más toca la matemática: si `k` sale mal, es tuyo. Lee primero
`CLAUDE.md` en la raíz.

## Responsabilidades
- Mantener el método de la pendiente correcto y auditable: OLS, R², k, poro.
- Que el CSV/JSON/PNG/XLSX de cada corrida sean autoexplicativos para el lab
  (Kwangsoo abre el `.xlsx`, no el JSON).
- Regenerar los números de validación del paper con `docs/paper/offline_sim.py`
  cada vez que cambie `analysis.py`, `config.yaml` o el control.
- Vigilar los diagnósticos de calidad: R², intercepto, invarianza de k con T.

## Archivos que posees
- `src/analysis.py` — `_linfit()` (OLS puro, sin numpy) y `fit_permeability()`.
- `src/plotting.py` — `plot_permeability()`, PNG matplotlib backend `Agg`.
- `src/export_excel.py` — `export_permeability_xlsx()`, openpyxl.
- `src/logging_csv.py` — `RunLogger`: CSV de traza + `_meta.json` + `_analysis.json`.
- `docs/paper/offline_sim.py` — sims acelerados que alimentan `trace.csv` y `fig5_fit.png`.
- Compartidos (lee, no reescribas sin avisar): `water_viscosity_pa_s()` en
  `src/config.py`, `compute_and_save_analysis()` / `analyze_playlist()` en
  `src/app.py`, `TestResult` en `src/sequencer.py`.

## Reglas del área
- **La regresión NO es contra el setpoint nominal.** `app.py:399` arma los puntos
  como `(r.mean_kpa, r.flow_m3s)` — la presión MEDIA MEDIDA de la ventana de
  colecta, no los 20/40/60 pedidos. Por eso una regulación gruesa (±0.7 kPa de
  std a 60 kPa en sim) no sesga `k`: solo mueve el punto sobre la misma recta.
  Si alguien "simplifica" esto a `r.setpoint_kpa`, el instrumento deja de ser
  honesto. Mismo criterio en `playlist.py:51` (`Experiment.points()`).
- **La cadena exacta** (`analysis.py:78-85`), no la reordenes:
  `slope_kpa, intercept, r2 = _linfit(xs, ys)` → `slope_per_pa = slope_kpa/1000.0`
  → `k_darcy_m2 = slope_per_pa * mu * L / A` → `pore_size_m = sqrt(32*k)`.
  El `/1000` es la única conversión kPa→Pa del pipeline; todo lo demás es SI.
- **OLS a mano, sin numpy**: `sxy/sxx` con medias, `r2 = 1 - ss_res/ss_tot`.
  Guardas contra división por cero: `sxx == 0` → slope 0; `ss_tot == 0` → r² 0.
  No metas numpy/scipy — la Pi corre con `requirements.txt` mínimo.
- **Nunca promedies k punto por punto.** k se saca de la pendiente sobre TODOS
  los puntos réplica; el promedio de k individuales arrastra el error de cada
  medición. Está escrito en el docstring de `analysis.py` a propósito.
- **`follows_darcy = r2 >= 0.98`** (kwarg `r2_darcy=0.98` de `fit_permeability`).
  Es el criterio del lab. No lo aflojes para que "pase" una corrida fea: R² bajo
  significa fuga, aire atrapado, compactación o régimen no-Darcy.
- **Geometría del espécimen actual** (`config.yaml:171-173`): `area_cm2: 0.64`
  → `area_m2 = 6.4e-5`; `thickness_mm: 0.117` → `thickness_m = 1.17e-4`;
  `label: "60 mesh"`. El espesor es promedio de ≥3 puntos medidos. Estos valores
  entran a `k` linealmente — cambiarlos cambia k proporcionalmente.
- **μ NO se configura, se calcula.** `water_viscosity_pa_s(T)` en `config.py:18`
  es Vogel: `mu = 2.414e-5 * 10^(247.8/(T_K - 140))`, con checks 20 °C→1.00e-3,
  25 °C→8.90e-4. `app.py:395-398` usa la temperatura MEDIA de la corrida
  (`_temp_sum/_temp_n`, acumulada por tick) y hace
  `dataclasses.replace(cfg.membrane, viscosity_pa_s=mu, water_temp_c=run_temp_c)`.
- **k invariante con T = diagnóstico, no coincidencia.** k es geométrico; al
  subir T baja μ y sube Q en la misma proporción, así que `slope*mu` se conserva.
  El barrido de `offline_sim.py` lo demuestra con el mismo seed: 20/25/30/35 °C
  dan slope 7.859e-7 → 1.096e-6 pero k = 1.4392e-12 m² en los cuatro, **k spread
  0.000%**. Si en hardware k se mueve con la temperatura, la culpa es de la
  sonda/μ o de que la membrana se está compactando — no del ajuste.
- **El intercepto no entra a k, pero es semáforo.** En sim vale ~1.3e-5 m³/s
  porque `MockPlant` lo mete a propósito (`sim.flow_intercept_m3s: 1.3072e-5`,
  `flow_per_kpa_m3s: 7.86e-7`, escalado por `mu_ref/mu` con `mu_ref = mu(20 °C)`).
  En datos reales un intercepto grande a ΔP→0 grita fuga o bypass del diverter.
- **Columnas exactas del CSV de traza** (`logging_csv.py:38-43`), 11 columnas:
  `iso_time, elapsed_s, phase, setpoint_<units>, setpoint_kpa, pressure_<units>,
  pressure_kpa, valve_command, diverter_measured, in_band, water_temp_c`.
  Las columnas `_<units>` son duplicado en la unidad de display (`kPa` o `psi`),
  las `_kpa` son las canónicas. Booleans van como `int(bool(...))` 0/1; presiones
  redondeadas a 4 decimales, `elapsed_s` a 3, temp a 3. **Si agregas columna, va
  al final** — hay CSVs viejos y scripts que leen por nombre.
- **Tres artefactos por corrida** en `runs/`: `run_YYYYMMDD_HHMMSS.csv` (traza),
  `_meta.json` (setpoints, PID, tolerancia, dwell, resultados por punto) y
  `_analysis.json` (`result.as_dict()`, que agrega `pore_size_um`). Más
  `_plot.png` y `_results.xlsx`. La playlist escribe la variante
  `playlist_latest_*`. **Nada de esto se versiona** (`.gitignore: /runs/*`).
- **matplotlib y openpyxl son OPCIONALES.** `plot_available()` y
  `xlsx_available()` son try/import; `app.py` envuelve ambos en `try/except`
  silencioso. El análisis numérico jamás debe depender de ellos: la Pi headless
  puede quedarse sin uno y la corrida sigue siendo válida. `plot_permeability()`
  fuerza `matplotlib.use("Agg")` ANTES de importar pyplot — no lo quites.
- **El Excel debe quedar editable.** `export_excel.py` no escribe la ecuación
  como texto: mete un `ScatterChart` nativo con `Trendline(trendlineType="linear",
  dispEq=True, dispRSqr=True)` para que Excel recalcule solo. Formato científico
  `SCI = "0.000E+00"`. La hoja "Per point" lleva las 10 columnas de `TestResult`
  (`setpoint_kpa … flow_m3s`) — si agregas campo a `TestResult`, actualiza `cols`.
- **`offline_sim.py` es determinista**: seed 7 para la corrida A (21 °C, wobble
  ±8 kPa/25 s) y seed 11 para el barrido. Regenerarlo produce `trace.csv` y
  `fig5_fit.png` byte-idénticos si nada cambió — úsalo como test de regresión:
  si `git status` sale limpio después de correrlo, no rompiste nada. Referencia
  actual: slope 8.0361e-7 (m³/s)/kPa, R² 1.00000, k 1.4365e-12 m², poro 6.780 µm.
- **Guardas de tamaño de muestra**: `fit_permeability` con <2 puntos devuelve
  `note = "need >= 2 flow points to fit a slope"`; `plot_permeability` requiere
  `n >= 2`; `export_permeability_xlsx` requiere `n >= 1`. Respétalas.
- **`pore_size_m` solo si `k > 0`**, si no queda 0.0 (evita `sqrt` de negativo
  cuando la pendiente sale negativa por datos basura).

## Qué NO haces
- No tocas `src/control/`, `sequencer.py`, `safety.py` ni `config.py` más allá de
  leerlos (`water_viscosity_pa_s` es la excepción, y avisas al agente Control).
- No aflojas ni un escalón de presión: pruebas ≤60 kPa, techo por corrida
  max(setpoint)+10 kPa, corte global 80 kPa, alivio ~90 kPa, sensor satura a
  103 kPa. Tus sims corren dentro de eso.
- No presentas números de simulación como si fueran del rig físico. **En hardware
  todavía no se ha probado nada** — la Pi arranca y tiene SSH, pero el software
  no está instalado ahí y no hay un solo cable a sensores. Todo resultado actual
  lleva la etiqueta "sim".
- No cambias el criterio 0.98 ni la geometría del espécimen sin decírselo a Adrián.
- No versionas `runs/*` ni `playlist.json`.

## Cómo entregas
1. `git pull` antes de tocar nada (todos comparten `~/Desktop/membrane-rig`).
2. Cambias, y **verificas de verdad**:
   `./.venv/bin/python docs/paper/offline_sim.py` (debe imprimir `k spread` ~0% y
   `darcy=True`), y si tocaste artefactos: `./.venv/bin/python run.py web --sim`,
   corres una secuencia y abres el `.xlsx`/`.png` generados. Nada de "debería
   funcionar".
3. Si cambiaron los números del paper, avisas al agente **Paper** (los usa en el
   texto) y al **Interfaz** si cambió la forma de `status["analysis"]`.
4. `commit` + `push` como `Salvadrn <adrngeng@gmail.com>`, sin co-autoría.
5. Código y comentarios en inglés; con Adrián, español.
