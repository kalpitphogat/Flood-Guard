# Five-minute demo script

Exact click order, the numbers to expect, what to say, and the three questions
judges will ask.

**Before you start:** `make serve` (one process: API + built dashboard on
:8000), or `make demo`. Run `python -m floodguard.cli demo --check` — every row
should be OK, including **Two-engine comparison**. Switch on **Demo Mode** in
the Simulation toolbar before the judges arrive, so a completed run is already
on screen.

---

## 0:00 — 0:30 · Frame the problem

> "Smart India Hackathon problem statement 26161 asks for dam-break inundation
> modelling of any river. Our position is that the deliverable is a running
> system whose numbers can be traced back to a file on disk — so everything
> you're about to see was computed, and anything that wasn't, says so."

Open **Home**. Point at the engine table at the bottom.

> "This table is probed from the machine, live. It says Delft3D binaries aren't
> installed here, and it names what runs instead. That's the honesty commitment
> this whole project is built on, and it's the first thing on the home page
> rather than a footnote."

---

## 0:30 — 1:15 · Configure a scenario

Go to **Simulation**. The Tehri scenario is preselected.

> "Tehri, on the Bhagirathi — not the Alaknanda; those meet at Devprayag to form
> the Ganga. India's tallest dam at 260 metres."

Open the **Scenario Configuration** panel. Point at the breach width field.

> "We haven't typed a breach width. The ghost hint is what Froehlich 2008
> predicts from the dam height and storage, live, before we commit to a run."

Point at the amber spread warning.

> "And this is the thing most dam-break tools hide. We run three published
> breach models, not one. On Tehri they disagree by a factor of **7.8** on
> width. That means breach geometry — not our solver — is the dominant
> uncertainty in the map you're about to see, and we'd rather tell you that
> than let you believe a number to three significant figures."

---

## 1:15 — 2:00 · Results

Flip the **Demo Mode** switch in the toolbar. It loads a completed run from
disk in a second — a run that `floodguard simulate` produced, not a canned
result. Do not run a fresh 6-hour simulation live.

Point at the four KPI cards.

> "Flooded area, maximum depth, maximum velocity, earliest arrival. Every one
> computed from the depth raster this run produced. Nothing here is a constant
> in the source."

Point at any card showing an em dash, if present.

> "Where something couldn't be computed it shows a dash, not a zero. Those are
> different statements. A building count of zero means we looked and found
> none; a dash means the layer never downloaded."

Point at the engine badge.

> "The badge reads *FloodGuard-SWE, Delft3D-class FV solver*. That string comes
> from the machine probe. There is no code path in the frontend that composes
> its own engine label."

---

## 2:00 — 2:45 · The map and the wave

Press **▶ Play** on the time slider.

> "Each step is a depth field the solver stored during the run — the raster
> itself is animating, served as tiles so the browser never downloads the
> grid. Towns turn blue as the computed wave reaches them: Devprayag, then
> Rishikesh, then Haridwar."

Switch the layer dropdown to **Flood arrival time**, then **Hazard class**.

> "Arrival time is what an evacuation plan runs on. Hazard is the Australian
> Disaster Resilience Handbook 7 classification — depth times velocity — so
> H5 and H6 mean buildings themselves are at risk, not just people."

Open the **3D View** tab and drag to tilt.

> "The terrain is the conditioned DEM the solver actually ran on, and the water
> is its computed surface. Dry cells aren't smoothed over to look continuous."

Point at the **cross-section** panel below.

> "Terrain in grey, maximum water level in blue, at each named town. Haridwar's
> section carries a caveat because the town sits 8 km off the traced channel, so
> that's a valley section, not a town section."

---

## 2:30 — 2:45 · Two engines, compared

Open **Comparison View**. Drag the swipe handle across the valley.

> "Left is our finite-volume solver, right is our SPH solver — particles, no
> mesh, no Riemann solver, completely different numerics, same physics, same
> grid, same breach. Where they agree we trust the answer more; where they
> don't, the difference raster shows exactly where. The table underneath is
> computed from both rasters: CSI of the extents, depth RMSE, and arrival at
> each town by each engine."

## 2:45 — 3:30 · The part that wins it — verification

Go to **About**, scroll to Validation. Or open `docs/validation/ritter_dam_break.png`.

> "This is the single most important slide. The black line is Ritter's 1892
> analytical solution for a dam break on a dry bed. The dashed blue line is our
> solver. Relative L2 error **0.503%**."

> "Stoker's wet-bed solution — which produces a real shock, so it tests the
> Riemann solver rather than just the rarefaction — **1.101%**, shock located
> within **0.06 cells**."

> "Lake at rest over rough terrain: spurious velocity **3.92 × 10⁻¹²** m/s. A
> scheme that isn't well-balanced produces metres per second of flow that
> doesn't exist, on every slope of a Himalayan DEM."

> "Seven checks, all passing, run by `make validate`, plots in the repository.
> And the SPH engine is held to the same exact solutions: Ritter at about 4%,
> Stoker at about 4%, and momentum conserved to 10⁻¹⁶ because every particle
> pair force is equal and opposite."

Then the sentence that matters:

> "Verification isn't validation. Passing these means our numerics are right.
> It says nothing about whether the DEM or the breach parameters describe the
> real river. We keep those two questions separate, and we say so in the
> methodology."

---

## 3:30 — 4:15 · Exports and the report

Click **Download as KML**, open it in Google Earth if available.

> "Time-stamped folders, so Google Earth animates the wave. That's what a
> district officer will actually open."

Click **Generate Report (PDF)**. Open it.

> "Six pages. Headline results, arrival sorted by lead time, all three breach
> predictions with their spread, exposure with every 'not computed' reason
> printed, the verification table, and a provenance block with the git commit
> on every page."

Scroll to section 8.

> "The caveats are in the body, not an appendix — including that the reservoir
> bathymetry is reconstructed rather than surveyed. A report that buries its
> limitations behind the maps is a report that gets quoted without them."

---

Click **Share link**.

> "A short link that reopens this exact view — run, layer, frame. Short enough
> to send by SMS to a district control room."

## 4:15 — 5:00 · Generality and close

Change the scenario dropdown to **Hirakud — Mahanadi**. Then flip the source to
**Any catalog dam** and open the dropdown.

> "Or any of the thirty dams in the CWC register — the DEM is fetched on the
> first run. And under Upload Custom Data, an agency can bring its own DEM, its
> own design hydrograph, or its district boundary; a file with no CRS, or a
> discharge column in cusecs, is refused with the reason, not silently
> converted."

> "Same code, different YAML. Tehri is 260 metres of head in a gorge: steep,
> fast, minutes of warning. Hirakud is 61 metres behind a 4.8 km embankment on
> a deltaic plain: twice the storage, a slower wave, hours of warning, far
> wider spread. Adding a dam is a file, not a code change."

Close with:

> "Thirty dams from the CWC register, each attribute cited to a page of a
> government PDF. A solver verified against analytical solutions. Honest labels
> where a third-party engine isn't installed. And a report a district disaster
> management officer could actually file."

---

## The three questions judges will ask

### 1. "Is this really Delft3D?"

**No, and the screen says so.**

> "Delft3D binaries aren't installed on this laptop. `/api/health/engines`
> probes for them, finds nothing, and every surface — the badge, the API
> response, the PDF cover — reads *FloodGuard-SWE, Delft3D-class FV solver*.
> There's a test in the suite that fails if any code path emits the string
> 'Delft3D' without a verified binary run."

Then turn it into a positive:

> "What we *do* generate is a complete, runnable D-Flow FM input deck — the
> UGRID network file, the .mdu, the boundary polyline, the .bc with the breach
> hydrograph, the DIMR config — from a DEM and a dam record. It's in the
> exports. That's days of work for a hydraulics team, and it runs the moment
> you point it at a licensed solver."

### 1½. "You said two engines — isn't that the same code twice?"

> "No. FloodGuard-SWE is Eulerian: a fixed grid, a Riemann solver at every
> face. FloodGuard-SPH is Lagrangian: water is 120,000 particles of fixed
> volume, depth is a kernel sum, there is no face and no Riemann solver. They
> share the DEM, the breach hydrograph and the equations — which is the point:
> the difference between them is numerical uncertainty, measured."

### 2. "How do I know the numbers are right?"

Two answers, in this order.

> "The numerics, we can prove: seven checks against exact analytical solutions,
> Ritter at 0.503% L2. `make validate` runs them in under a minute."

> "The inputs, we can't prove — so we qualify them. The reservoir bathymetry is
> reconstructed, not surveyed; the DEM is a surface model that reads canopy top;
> Manning's n is uniform without a land-cover raster. Each of those is a warning
> attached to the run, and each appears in the report. The one independent check
> we do have is that the reconstructed reservoir bed lands within 2 metres of
> crest elevation minus the registered dam height — two completely separate data
> paths agreeing."

### 3. "Does it work for any river, or just the one you tuned?"

> "Adding a dam is a YAML file. The two demo scenarios are deliberately opposite
> regimes — a 260 m Himalayan gorge and a 61 m deltaic embankment — and the same
> code runs both. The catalog has 30 dams across 25 rivers."

If pressed on what would break:

> "Honestly: a dam whose FRL isn't in the NRLD. We refuse to run rather than
> guess a reservoir level, so you'd get a 422 telling you to supply it. And a
> concrete arch dam, where all three breach models are marked inapplicable —
> they're embankment-erosion regressions and a concrete dam fails by structural
> collapse. We flag it rather than returning a number that looks authoritative."

---

## If something goes wrong

| Symptom | Do this |
| --- | --- |
| Backend unreachable | `make serve-backend`; Home shows a clear error, not a blank page |
| No venue Wi-Fi | Everything after `make data` is offline. Use a precomputed run |
| A live run is slow | Say why: 30 m over 120 km is ~50,000 timesteps. Switch to 90 m and say that resolution is exposed because peak depths genuinely depend on it |
| Exposure cards all show dashes | Correct behaviour — OSM/WorldPop weren't fetched. Say so; it's the rule working |
| Someone asks "is that real SPH?" | Yes — Lagrangian particles, Wendland kernel, Monaghan viscosity, verified against Ritter and Stoker. It is *depth-integrated* SPH, not a 3D WCSPH of the breach face; the label says so. PySPH/DualSPHysics would add the 3D near field, and the DualSPHysics CaseDef is generated |
| Comparison tab is empty | The loaded run had one engine. Pick a run in Demo Mode whose label shows `swe_fv + sph_swe` |
| 3D tab says "no bed.tif" | The run predates the 3D view; load a newer run |

**Never** run a fresh full-resolution simulation live. Load a precomputed run.
