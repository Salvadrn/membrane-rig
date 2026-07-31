# ENLACE 8-minute talk

Deliverable: an 8-minute talk on the summer's work — the technical experiment and the
Kwangsoo project it sits inside. Audience: undergraduate summer-research program, mixed
background. The material is all from `docs/paper/`; the job was to **cut**, not gather.

## The three pieces

- **`slides.md`** — the canonical slide content (10 cards), deliberately sparse. Source of truth.
- **`script.md`** — the presenter guion: what to say on each slide, timed to 8:00, with
  cut/expand lists and figure cues. **This is the part to rehearse from.**
- **The Gamma deck** — generated from `slides.md`. Direction "Pizarra": theme `onyx`
  (black-and-white, high contrast, bold), 16:9.
  - Deck: https://gamma.app/docs/rguwb2l0i0i88fn
  - Type: Montserrat 700 headings, Source Sans 3 body, near-white `#E2E6E9` on `#111213`.
    Want the body heavier still? Bump the body weight in the Gamma editor — the theme carries
    Source Sans 3 at weights 200–900, so 600 is one click away.
  - Superseded: an earlier `default-dark` version at `gamma.app/docs/o8btp682u3sjeqn` — delete it
    in Gamma so there's no confusion about which deck is current.

## Design notes

**Type size is controlled by word count.** Gamma scales text to fit the card, so the slides are
cut to a few short lines each — that is what makes the type large and heavy. If you add
sentences, the type shrinks. Cut instead, and put the detail in `script.md`.

**Theme `onyx`** was picked over `default-dark` for exactly this: pure b&w, bold, high-contrast,
minimal — legible from the back of a lecture hall.

## Insert the paper figures in the Gamma editor

The deck was generated with **image placeholders** (`imageOptions.source: placeholder`), so the
layout already reserves the space — no AI-generated art, nothing fabricated. Drop these in:

| Slide | Figure | What it shows |
|---|---|---|
| 5 · Darcy as a slope | `fig5_fit.png` | the actual Q-vs-ΔP fit the instrument produces |
| 7 · The system | `fig1_system.png` | the system block diagram |
| 8 · Validation | `fig4_sequence.png` | the 20/40/60 kPa run: pressure flat, disturbance in the valve |

Delete any placeholder you don't fill.

## Editing

The Gamma API can only **create**, not edit. So:
- Tweaks (wording, layout, dropping figures in) → the Gamma editor.
- A content overhaul → edit `slides.md` and re-generate (produces a **new** deck / URL).

## How it was generated (to regenerate)

Gamma MCP `generate`, from the body of `slides.md`: `textMode: preserve` (verbatim — protects the
numbers), `cardSplit: inputTextBreaks` (`---` = card break), `themeId: onyx`,
`cardOptions.dimensions: 16x9`, `imageOptions.source: placeholder`, `textOptions.language: en`,
plus `additionalInstructions` asking for maximum type weight and two-column layouts with a
reserved image area on the three figure slides.

## Notes

- **Language: English** — matches the paper and the UCSD venue. If Adrián presents in Spanish,
  flip both `slides.md` and `script.md` and regenerate.
- **Every number is from simulation.** They trace to `docs/paper/`; keep them in sync if the paper
  changes. The golden rule is said out loud on the title and slide 8 — that's deliberate.
- **Slide 2 (Kwangsoo context)** is written from the paper's one-liner; enrich it once Adrián
  gives the device / research question / where his measurement fits.
