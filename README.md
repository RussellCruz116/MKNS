# MaKeNeS (Mobility Agents and Kinematic Environment Network Simulator)

Welcome to the **MaKeNeS Framework**, developed for the Asian Development Bank's **AI for Safer Roads Innovation Challenge**.

MaKeNeS is a predictive digital twin that simulates microscopic, sub-lane traffic kinematics to calculate empirical **Speed Safety Scores ($S^3$)** across entire national road networks.

**Live demo:** [Live Interactive Safety Map](https://RussellCruz116.github.io/MKNS/)

---

## Reviewer Fast Path

1. Open the [Live Interactive Safety Map](https://RussellCruz116.github.io/MKNS/), or open `docs/index.html` from a local static host.
2. Inspect the three deliverables in the table below.
3. Read [`SPEED_SAFETY_SCORE.md`](SPEED_SAFETY_SCORE.md) for the mathematical methodology.
4. Use `outputs/reports/ministerial_report.md` for the policy-facing interpretation.

---

## Three Required Deliverables

| ADB deliverable | Where to review | What is included |
|---|---|---|
| **Analytical Model** | [`prototypes/analytical_model/abm_engine.py`](prototypes/analytical_model/abm_engine.py), [`process_documentation/02_agent_based_modeling.md`](process_documentation/02_agent_based_modeling.md) | Agent-based traffic simulation on road-network geometries, with Cars, HGVs, Pedestrians (4 demographic profiles), Cyclists, and PTWs. Conflicts are logged using TTC and PET surrogate safety measures. |
| **Speed Safety Score** | [`SPEED_SAFETY_SCORE.md`](SPEED_SAFETY_SCORE.md), [`prototypes/speed_safety_score/scoring_documentation.md`](prototypes/speed_safety_score/scoring_documentation.md), [`prototypes/speed_safety_score/score_calculator.py`](prototypes/speed_safety_score/score_calculator.py) | Transparent 0–100 score combining kinematics, friction, VRU exposure, speeding, contextual AI evaluation, and simulated stress. Lower scores indicate higher priority for speed review or intervention. |
| **Geospatial Visualization** | [`docs/index.html`](docs/index.html), [`prototypes/geospatial_model/map_generator.py`](prototypes/geospatial_model/map_generator.py) | Static-hostable MapLibre dashboard with chunk-loaded access to the full scored network. The initial view loads a compact Top 100 layer, then fetches full cluster GeoJSON files on demand. |

---

## Quickstart

```bash
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Set `GEMINI_API_KEY` in a `.env` file for AI evaluator features (optional for map-only rebuild).

### Option A — Full pipeline (~4.5 hours, 70k segments)

Runs ABM, scoring, SQLite persistence, ministerial report, and What-If maps:

```bash
python prototypes/main.py
```

### Option B — Fast pipeline run (~5 minutes, 70k segments)

Uses already cached spatial/Mapillary/HeiGIT data in the DB to skip the 4-hour geospatial enrichment queries. It re-runs the entire parallelized ABM traffic simulation on all 70k segments, computes S³ safety scores, and regenerates the geospatial dashboard:

```bash
python prototypes/main.py --skip-enrichment --sim-mode rush_hour
```

### Option C — Fast dashboard rebuild (~1 minute)

Uses existing `makenes_scored.geojson` + `db/makenes.sqlite` cache. Re-simulates Top 5 segments for ABM video replay only:

```bash
python generate_dashboard.py
```

### Option D — GitHub Pages demo

Generates a lightweight map in `docs/` for public hosting:

```bash
python generate_dashboard.py --demo
```


### Reproducible runs

```bash
# Linux/macOS
MAKENES_DETERMINISTIC=1 python prototypes/main.py

# Windows PowerShell
$env:MAKENES_DETERMINISTIC = "1"
python prototypes/main.py
```

Fixes ABM random seeds and caches LLM evaluator responses in `data/cache/board_evaluations.json`.

---

## Core Features

- **High-Density Rush Hour & Full-Day ABM:** Choose between `rush_hour` (peak volumes) or `full_day` time-of-day traffic profiles.
- **HeiGIT predicted road surface & smoothness** integrated into S³ scoring and ABM vehicle speed damping.
- **Interactive Infrastructure Pins:** Toggleable pins on the map identifying crosswalks, sidewalks, cycleways, lighting, traffic calming, and unpaved surfaces.
- **VRU coverage:** Pedestrians, cyclists, and PTWs in ABM with distinct conflict logging.
- **Top 100 Priority dashboard** with violated Safe System rules and Safety ROI.
- **ABM canvas replay** on the 5 most hazardous segments.
- **What-If scenario map:** `makenes_whatif_safety_map.html`.

## Hiding Past Commits and Fixing GitHub Pages Size Limits

If your GitHub Pages deployment is empty or failing to build because the repository size has become too large from frequent commits of large map files (`.geojson`), you can reset the Git history and wipe old deployments.

### 1. Resetting Git History (Wipe Past Commits)

Run the following commands in your terminal to create a fresh Git history with only your current files:

```bash
# 1. Checkout a temporary orphan branch
git checkout --orphan temp_branch

# 2. Add all current files (respecting the new .gitignore)
git add .

# 3. Commit the current state
git commit -m "Initial commit: Clean state"

# 4. Delete the old main branch
git branch -D main

# 5. Rename the temporary branch to main
git branch -m main

# 6. Force push to the remote repository to overwrite history
git push -f origin main
```

### 2. Clearing Old GitHub Pages Deployments

If you use GitHub Actions to deploy GitHub pages, you should also clear out old action runs that might be storing massive artifacts:

1. Go to your repository on GitHub.
2. Click on the **Actions** tab.
3. Click on **pages-build-deployment** (or your deployment workflow) on the left sidebar.
4. You can manually delete old workflow runs by clicking the three dots `...` next to a run and selecting **Delete workflow run**.

*Note: The `.gitignore` has been updated to ignore the `prototypes/` and `tests/` folders to further reduce repository size upon pushing.*
