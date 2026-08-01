# ENLACE 8-minute talk

Deliverable: an 8-minute talk on the summer's work — the technical experiment and the
Kwangsoo project it sits inside. Audience: undergraduate summer-research program, mixed
background. The material is all from `docs/paper/`; the job was to **cut**, not gather.

## The three pieces

- **`slides.md`** — the canonical slide content (11 cards), deliberately sparse. Source of truth.
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

## The figures — talk versions, not the paper's

**Do not use `docs/paper/fig1–fig5`.** A paper figure is read at 30 cm with time; a talk figure is
read from the back of the room in the ~8 seconds the audience spares while also listening. And the
paper's are black-on-white — a white rectangle on a dark slide glares in a darkened room.

`gen_talk_figs.py` (in this folder) draws five purpose-built ones: transparent background, light
ink, large type, one idea each. It is **separate from `../paper/gen_figs.py` on purpose** — that one
feeds the .docx and must keep its white background. Don't merge them.

```bash
./.venv/bin/python docs/talk/gen_talk_figs.py
```

The deck was generated with **image placeholders**, so the layout already reserves the space — no
AI-generated art, nothing fabricated. Drop these into the Gamma editor:

| Slide | Figure | The one idea |
|---|---|---|
| 2 · what a permeability test is | `talk_test_concept.png` | pressure in, membrane, water out — measured over a known time |
| 5 · the core idea | `talk_scatter_vs_bias.png` | scatter the fit survives vs bias it can't undo (schematic) |
| 6 · Darcy as a slope | `talk_fit.png` | the line, the points, k and R² |
| 7 · it checks itself | `talk_temperature.png` | raw slope +39%, k dead flat |
| 8 · the system | `talk_system.png` | just the two loops — pressure, and collection timing |

Slides 1, 3–4 and 9–11 are text only — delete their placeholders.

**Slide 2 was added in the Gamma editor, not by regenerating.** Two reasons: a fresh `generate`
caps at 10 cards, and regenerating mints a new deck URL and would discard the figures already
dropped in. `slides.md` still holds its text as the source of truth.

**Where the numbers come from:** the fit and temperature figures use `offline_sim.py`'s own stdout
(the paper's RUN A and temperature sweep), so the talk cannot contradict the paper. The
scatter-vs-bias one is schematic — it illustrates an argument, it is not data, and it is labelled
that way in the source. Re-run `offline_sim.py` and update the constants at the top of
`gen_talk_figs.py` if the control code ever changes.

## On the day: the cue card

`cue-card.html` — one page, printable (⌘P), readable on a phone. The clock, the opening line of
every slide, and the numbers that can't be improvised. `script.md` is for rehearsing at home; the
cue card is for standing up in front of people at minute three having lost the thread.

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
  changes. The golden rule is said out loud on the title and slide 9 — that's deliberate.
- **Slide 3 (Kwangsoo context)** is written from the paper's one-liner; enrich it once Adrián
  gives the device / research question / where his measurement fits.
