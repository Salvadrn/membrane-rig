# Paper — system description

`Automated_Membrane_Permeability_System_Martinez.docx` — scientific-paper-style write-up
of how the rig and its software work (author: Salvador Adrián Martínez García).
14 pages: theory (Darcy slope method, pore size, viscosity/temperature), signal
chains with worked numbers, the discrete PID law term by term, the test-sequencing
state machine, analysis pipeline, simulation validation, safety design, and remote
operation.

Everything here is regenerable, so edit the sources rather than the `.docx` if the
system changes:

```bash
python offline_sim.py   # re-runs the accelerated validation sims -> trace.csv,
                        # fig5_fit.png, and the numbers in Tables 1-2 / Sec. 7
python gen_figs.py      # redraws fig1 (block diagram), fig2 (layer map),
                        # fig3 (control loop), fig4 (annotated timeline from trace.csv)
npm install docx        # once, if not already present
node gen_paper.js       # rewrites the .docx in this folder, embedding all figures
```

Run them in that order when the control code or config changes: offline_sim feeds
fig4/fig5 and the validation tables. All results in the paper are **simulation-based**
(stated explicitly in Secs. 7 and 10); the hardware-validation content must be added
once the rig is commissioned.
