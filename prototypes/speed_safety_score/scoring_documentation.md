# Speed Safety Score ($S^3$) — Official Methodology

> **Authoritative reference:** This document is the plain-language companion to [`SPEED_SAFETY_SCORE.md`](../../SPEED_SAFETY_SCORE.md) and the implementation in [`score_calculator.py`](../speed_safety_score/score_calculator.py).

The Speed Safety Score ($S^3$) is designed for non-technical policymakers (e.g., transport ministry officials) to interpret the kinetic risk of any road segment on a **0–100 scale**, where **100 is perfectly Safe System aligned** and **0 is the most deadly**.

---

## How the Score is Calculated

Each segment receives a score derived from six penalty categories. Category maximums adapt to the segment's `LandUse`, `RoadClass`, and posted speed limit, but always sum to 100 points before blending.

### The Six Categories

| Category | What it measures | Primary data source |
|----------|------------------|---------------------|
| **Kinematic Severity** | Fatality probability from operating speeds vs. survivable thresholds | GPS telemetry ($V_{85}$, median speed), Wramborg (2005) curves |
| **Contextual Friction** | Missing protective infrastructure (medians, edge delineation, narrow lanes) | Mapillary visual friction |
| **VRU Exposure** | Near-misses between vehicles and vulnerable road users | ABM: TTC & PET for pedestrians, cyclists, PTWs |
| **Behavioral Speeding** | Share of vehicles exceeding the posted limit | Probe telemetry (`PercentOverLimit`) |
| **Safety Experience (AI)** | Contextual policy evaluation (school zones, density, regional norms) | Board of Evaluators (LLM + heuristics) |
| **Active Road Stress** | Hard braking and high-stress deceleration events | ABM stress logs |

### Core Formula

$$ S^3 = 100 \times \left( W_{linear}(1 - P_{total}) + W_{exp}(1 - P_{total})^\gamma \right) $$

- $P_{total}$ — aggregated, 99th-percentile-capped penalty from all six categories (0–1)
- $\gamma$ — Wramborg penalty exponent: **1.5** on motorways, **2.0** in urban VRU-dense zones
- Each category uses a **50/50 blend** of linear and convex exponential decay

### Safe System Violations

When a segment exceeds its dynamic survivability limit, the dashboard lists explicit violated rules with citations (e.g., WHO Safe System 2022, Wramborg 2005, FHWA SSAM, AASHTO clear-zone guidelines).

---

## What the Score Means

| Score | Classification | Recommended action |
|-------|----------------|--------------------|
| **76–100** | Lower modelled concern | Monitor; validate with local crash or speed survey data |
| **51–75** | Moderate concern | Targeted enforcement, limit review, or localized calming |
| **26–50** | High concern | Corridor review and targeted countermeasures |
| **0–25** | Severe mismatch | Immediate speed-limit and infrastructure intervention |

The interactive map colors every segment on this continuous gradient and ranks the **Top 100 Priority** segments for ministerial review.

---

## Reproducibility

- **Deterministic physics:** Set `MAKENES_DETERMINISTIC=1` before running the pipeline to fix random seeds in the ABM.
- **Cached AI evaluations:** With `MAKENES_LLM_CACHE=1`, Board of Evaluator LLM responses are read from `data/cache/board_evaluations.json` instead of calling the API.
- **Full audit run:** `python prototypes/main.py` (~4.5 hours on 69,966 segments)
- **Fast dashboard rebuild:** `python generate_dashboard.py` (uses SQLite cache + Top 5 ABM replay, ~1 minute)

See [`DEPLOYMENT.md`](../../DEPLOYMENT.md) for GitHub Pages hosting and demo map generation.
