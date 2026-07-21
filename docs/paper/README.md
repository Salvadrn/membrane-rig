# Paper — system description

`Automated_Membrane_Permeability_System_Martinez.docx` — scientific-paper-style write-up
of how the rig and its software work (author: Salvador Adrián Martínez García).

Everything here is regenerable, so edit the sources rather than the `.docx` if the
system changes:

```bash
python gen_figs.py     # redraws fig1_system.png (block diagram) + fig2_software.png (layer map)
npm install docx       # once, if not already present
node gen_paper.js      # rewrites the .docx in this folder, embedding both figures
```

Numbers quoted in the paper come from the simulation runs and the reference 60-mesh
dataset — see `README.md` at the repo root and `docs/ASSEMBLY.md`. All results in the
paper are **simulation-based**; the hardware-validation section must be updated once
the rig is commissioned.
