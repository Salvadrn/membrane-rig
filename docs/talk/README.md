# ENLACE 8-minute talk

Deliverable: an 8-minute talk on the summer's work — the technical experiment and the
Kwangsoo project it sits inside. Audience: undergraduate summer-research program, mixed
background. The material is all from `docs/paper/`; the job was to **cut**, not gather.

## The three pieces

- **`slides.md`** — the canonical slide content (10 cards). This is the source of truth; edit
  it if the content changes.
- **`script.md`** — the presenter guion: what to say on each slide, timed to 8:00, with
  cut/expand lists and figure cues. **This is the part to rehearse from.**
- **The Gamma deck** — generated from `slides.md`. Direction "Pizarra" (dark, high-contrast,
  one idea per slide), theme `default-dark`.
  - Deck: https://gamma.app/docs/o8btp682u3sjeqn
  - Open it in the Gamma editor to insert the figures below and make any tweaks.

## Insert the paper figures in the Gamma editor

Gamma can't pull local PNGs, so it was generated text-only (no fabricated diagrams). Drop these
three figures from `docs/paper/` into the editor — everything else is typographic and needs nothing:

| Slide | Figure | What it shows |
|---|---|---|
| 5 · Darcy as a slope | `fig5_fit.png` | the actual Q-vs-ΔP fit the instrument produces |
| 7 · The system | `fig1_system.png` | the system block diagram |
| 8 · Validation | `fig4_sequence.png` | the 20/40/60 kPa run: pressure held flat, disturbance in the valve |

## Editing

The Gamma API can only **create**, not edit. So:
- Small tweaks (wording, layout, dropping the figures in) → do them in the Gamma editor.
- A content overhaul → edit `slides.md` and re-generate (produces a **new** deck / URL).

## How it was generated (to regenerate)

Gamma MCP `generate`, from the body of `slides.md`: `textMode: preserve` (verbatim — protects the
numbers), `cardSplit: inputTextBreaks` (`---` = card break), `themeId: default-dark`,
`cardOptions.dimensions: 16x9`, `imageOptions.source: noImages`, `textOptions.language: en`.

## Notes

- **Language: English** — matches the paper and the UCSD venue. If Adrián presents in Spanish,
  flip both `slides.md` and `script.md` and regenerate.
- **Every number is from simulation.** They trace to `docs/paper/`; keep them in sync if the paper
  changes. The golden rule is said out loud on the title and slide 7 — that's deliberate.
- **Slide 2 (Kwangsoo context)** is written from the paper's one-liner; enrich it once Adrián
  gives the device / research question / where his measurement fits.
