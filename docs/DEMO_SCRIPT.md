# Five-minute demo script (preset flow)

Exact click order, what to say, and the questions judges will ask. **Every
number below was measured from the six precomputed preset runs of 2026-09-30
(120 m, FloodGuard-SWE) or from `floodguard validate` on the final code.** If
you recompute anything, re-read the numbers from the dashboard, not from here.

**Before you start**
1. `python -m floodguard.cli pack import floodguard_demo_presets_120m.fgpack`
   (once, on the demo laptop; see `docs/HANDOFF.md` R3.5).
2. `make serve` → http://localhost:8000. Open **Simulation**. The input panel
   opens on **Preset — instant**.
3. Check: all three reservoir levels are selectable for both dams; the two
   other failure types are greyed out with "not precomputed yet".

---

## 0:00 — 0:30 · Frame the problem

> "Problem statement 26161: dam-break inundation modelling for any river. What
> you'll see are real, full-pipeline runs, computed ahead of time and labelled
> with the date they were computed — plus a live quick mode for anything else,
> labelled as coarse. Nothing is presented as something it isn't."

Open **Home** and point at the engine table.

> "Probed live from this machine. No Delft3D binary here, so the tool says so,
> and names the solver that actually runs."

---

## 0:30 — 1:30 · A preset, instantly

In **Precomputed Scenarios**: Dam = Tehri, Failure type = Complete dam break,
Reservoir level = **Full reservoir level (FRL) — 830.00 m**. Click **Show
precomputed result**.

Point at the green badge above the map: *Precomputed on 2026-09-30 · 120 m · 6 h simulated*.

> "This loaded in about a second because it was computed ahead of time — it
> took 178.5 seconds of solver time. The badge says exactly that; we never
> present a stored run as computed now."

Point at the KPI cards.

> "154.8 square kilometres flooded, first arrival 10 minutes after the breach
> starts. The breach releases 3,526 million cubic metres — that matches the CWC
> register's 3,540 to within half a percent, because the reservoir bed under
> the lake surface is reconstructed and calibrated to it. The run says so in
> its warnings."

Switch the level to **Minimum drawdown level (MDDL) — 740.00 m**.

> "Same dam, reservoir drawn down: 28.1 square kilometres, and the wave reaches
> Devprayag at 159 minutes instead of 90. Reservoir level changes the answer —
> which is why it's a choice here and not a constant."

---

## 1:30 — 2:15 · The wave, and the tools a control room uses

Press **▶ Play**, then click **4×**.

> "Each frame is a depth field the solver stored. The speed control only
> changes how fast we step through them."

Open **Export** → **Wave animation KMZ (per frame)**, open it in Google Earth
if available.

> "Every frame's wet area as its own time span, so Google Earth's slider shows
> the flood arriving and draining, not just its maximum."

Point at the **Early Warning** panel and the Hindi bulletin button.

> "Alert level per town, nearest safe ground, a Hindi bulletin and a CAP 1.2
> file marked Exercise — issuing an actual alert is an authority's decision."

---

Scroll to **Town Gauges** and click **Rishikesh**.

> "Two curves: the town's own point, which stays dry because it sits 2.3 km
> from the river, and the river beside the town, which the flood reaches at
> 264 minutes and is still rising when the six-hour run ends. We show both,
> because the town row alone would have said 'not reached'."

Scroll to **What Matters Most**.

> "Each breach input moved alone across the range the published models
> themselves disagree over. For Tehri the formation time dominates the peak;
> for Hirakud it is the breach width. That is where better data would help most."

## 2:15 — 3:00 · Consequences, with the method on the page

Scroll to **Loss-of-Life Estimate**.

> "Graham 1999, the US Bureau of Reclamation method, with the rate table
> transcribed from the report itself. Warning issued when the breach starts:
> between 813 and 8,840 people, of 148,354 modelled residents in the flooded
> area. It's a range, it says it's a planning estimate and not a prediction,
> and it's only in the officials' section of the bulletin — never in the SMS."

Change *Warning issued* to **1 h after breach starts (night)**.

> "An hour's delay: 1,436 to 16,851. That's the argument for early warning, in
> the method's own numbers."

---

## 3:00 — 3:30 · Generality: the opposite river

Dam = **Hirakud**, level FRL (192.02 m).

> "Same code, a YAML file of difference. Hirakud is 61 metres of head on a flat
> plain: the peak discharge comes at 530 minutes instead of 80, 1,438 square
> kilometres flooded, Sambalpur reached after 494 minutes. The FRL run took
> 428 seconds on our server; you're seeing it instantly."

---

## 3:30 — 4:15 · Anything else: quick estimate, live

Switch to **Custom — quick estimate**. Pick a scenario, change the reservoir
level, click **Run quick estimate**.

> "Anything that isn't a preset runs live — at 200 metres, for one simulated
> hour, and it's labelled exactly that on the map, in the result file and in
> the PDF. Coarser, but honest about it."

When it finishes, point at the amber badge: *Quick estimate · 200 m · 1 h simulated*.

---

## 4:15 — 5:00 · Why the numbers can be trusted — and what we fixed

Go to **About** → Validation (or `docs/validation/`).

> "The solver is checked against exact solutions: Ritter's dam break at 0.305%
> error, Stoker's at 0.725% with the shock within 0.4 cells, still water over
> rough terrain staying still to 4 × 10⁻¹², and Thacker's oscillating bowl —
> a moving shoreline on a curved bed — with the period right to 0.01%."

Then the sentence that matters:

> "And when our first real runs looked wrong — 339 metres of water at
> Devprayag — we didn't tune it away. We found four bugs, including two that
> created water, fixed them, and now every run reports its mass balance: Tehri
> closes to 0.03% with zero water created. The runs you just saw are the fixed
> ones."

---

## Questions judges will ask

### "Where does this number come from?"
Open **Provenance** → **Show all**: every value with the file and field it was
read from, and the cautions first (reconstructed bathymetry, the FRL/MDDL values
that are not in the NRLD tables).

### "Is this Delft3D?"
No, and every surface says so: *FloodGuard-SWE (Delft3D-class FV solver)*. A
complete D-Flow FM input deck is generated as an export; it runs when a
licensed `dflowfm` is present.

### "Why only complete dam break?"
> "Overtopping is still the same computation as a complete break in our
> breach model, so we list it as 'not modelled distinctly yet' rather than show
> the same numbers under another name. A partial breach *is* modelled — you set
> how deep the breach cuts as a fraction of the dam height, and the pool below
> that stays behind — but it runs live, not as a preset, because that fraction
> is your assumption: no published model predicts it, and the result says so."

### "How accurate are the depths at the towns?"
> "The towns' rows are taken on the traced channel; when a town sits kilometres
> off it — Rishikesh 2.3 km, Haridwar 7.1 km — the run says the depth is a
> valley depth, not a street depth. At 120 m, a narrow gorge like Devprayag's
> is averaged into large cells, so peak depths there are an upper-range
> estimate we haven't checked against an independent study. The 30 m run is the
> publication setting."

### "What about river blockages — landslide dams?"
> "A natural blockage is its own dam type: the embankment breach formulas don't
> apply, so we require the breach size and timing as inputs and cross-check the
> routed peak against Costa's 1985 USGS regression for landslide dams. The
> barrier is raised into the terrain the solver runs on, wall to wall across
> the valley, so the flood can't spill back into the empty lake bed, and the
> lake's storage is counted above the river's pre-event surface. It's tested on
> real terrain with a hypothetical barrier; it's not in the preset list."

### "Two engines?"
> "The second engine, FloodGuard-SPH, is verified on analytical cases, but one
> of its checks currently fails after a settings change, so the presets use the
> finite-volume engine only. We show that failure in the validation table
> rather than hide it."

---

## If something goes wrong

| Symptom | Do this |
| --- | --- |
| A preset shows "not precomputed yet" | The pack wasn't imported on this machine: `python -m floodguard.cli pack import floodguard_demo_presets_120m.fgpack` |
| Loss-of-life says "not computed" | Normal for a warning time other than −60/0/+60 min on a laptop without the WorldPop raster; use one of the three offered |
| Quick estimate is slow | It downloads the DEM for a new dam on first use (needs internet). Use a bundled scenario |
| Comparison tab is empty | Presets are single-engine by design; say so |

**Never** start a full-resolution run live. Use a preset, or the quick estimate.
If a live run is taking too long, press **Stop run**: the run's process is ended
at once and nothing from it is shown. Restarting the server does not kill a
running estimate; it is picked up again when the server comes back.
