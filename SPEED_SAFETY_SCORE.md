# The Speed Safety Score (S³) Architecture

The Speed Safety Score ($S^3$) is the foundational metric of the MaKeNeS framework. It transforms highly localized, empirical data (derived from the Mapillary API and ABM Agent simulations) into a standardized 0-100 risk score, where 0 is the highest priority for intervention and 100 is strongly aligned with Safe System principles.

It fulfills the ADB Innovation Challenge criteria for a **"predictive analytical model measuring Safe System alignment."**

## Core Formula

The S³ relies on a multi-dimensional penalty architecture:

$$ S^3 = 100 \times \left( W_{linear}(1 - P_{total}) + W_{exp}(1 - P_{total})^\gamma \right) $$

Where:
- $P_{total} \in [0, 1]$ is the aggregated, Min-Max normalized cumulative penalty from 7 core categories.
- $W_{linear}$ and $W_{exp}$ are context-dependent linear and exponential weight shares (sum to 1.0).
- $\gamma$ is the **penalty exponent**, calibrated based on regional functional class.

### 1. Context-Dependent Weights & Exponent ($\gamma$)

| Road Context | $W_{linear}$ | $W_{exp}$ | $\gamma$ |
|---|---|---|---|
| Motorway / ≥ 80 km/h | 0.5 | 0.5 | 1.0 |
| Low-speed VRU zones (≤ 30 km/h, residential) | 0.3 | 0.7 | 1.0 |
| General urban / rural | 0.4 | 0.6 | 1.0 |

With $\gamma = 1.0$, the formula reduces to a weighted linear blend of penalty — intentionally designed to be auditable and interpretable by transport ministry officials without non-linear distortion.

### 2. Kinematic Fatality Probability — Dual-Curve Calibration

The Kinematic Severity index uses **two distinct logistic fatality curves** calibrated by road function:

- **Pedestrian survivability curve** (urban / local roads) — based on Wramborg (2005):
  $$P_{fatal} = \frac{1}{1 + e^{-(-8.35 + 0.099 \times V_{85})}}$$

- **Occupant frontal crash curve** (motorways / ≥ 80 km/h):
  $$P_{fatal} = \frac{1}{1 + e^{-(-8.91 + 0.044 \times V_{85})}}$$

This prevents over-penalizing motorways using pedestrian-fatality physics.

### 3. The 7-Category Penalty Matrix ($P_{total}$)

The total penalty is composed of 7 normalized categories, each with a **dynamic maximum allocation** that adapts row-by-row based on the segment's `LandUse`, `RoadClass`, and posted speed limit:

1. **Score_Kinematics ($P_{kin}$):** Based on $V_{85}$, fatality probability curve, and Kinetic Risk Delta. V2V rear-end conflicts add a direct kinetic penalty.
2. **Score_Friction ($P_{fric}$):** Derived from Mapillary visual friction proxies, blended with POI densities (markets, transit), and the Safe System Risk Delta.
3. **Score_VRU ($P_{vru}$):** Derived from the ABM. Penalizes VRU-vehicle TTC conflicts (×5) and PET near-misses (×6). Penalty logic multiplies severity by 1.5x–2.0x in close proximity to sensitive POIs (Schools, Hospitals).
4. **Score_Speeding ($P_{spd}$):** The statistical proportion of vehicles exceeding the posted limit (softened 1.5× on motorways).
5. **Score_AI ($P_{ai}$):** The LLM-evaluated contextual Board of Evaluators penalty. Interprets school zone proximity, urban density, and regional guidelines.
6. **Score_Stress ($P_{strs}$):** Log-scaled ABM hard-braking and high-stress deceleration events (log ceiling at 10 events).
7. **Score_Infrastructure ($P_{infra}$):** Directly derived from OSM & Mapillary.
   - **Hazards (+Penalty):** "Infrastructure Deficits" (e.g., dense `UrbanCentre_Pop` combined with missing sidewalks or zero crosswalks) heavily penalize the road.
   - **Safety Bonuses (-Penalty):** Presence of `OSM_Sidewalks`, `OSM_Cycleways`, `Mapillary_Crosswalks`, or `OSM_StreetLighting` reduce the overall penalty to reward protective infrastructure.

### 4. Normalization (The 99th Percentile Ceiling)

To prevent severe outliers from artificially compressing the rest of the dataset into a narrow band, raw penalties are capped at the 99th percentile before Min-Max scaling:

$$ P_{normalized} = \frac{ \min(P_{raw}, P_{99th}) }{ P_{99th} } $$

This guarantees that the worst 1% of roads max out their penalty buckets at 100%, allowing the other 99% to spread organically across the scale for actionable geospatial clustering.

### 5. Data Confidence Regression

Scores for segments with low telemetry sample sizes are regressed toward a safe median to prevent unwarranted extreme scores:

$$ S^3_{final} = S^3_{raw} \times \text{confidence} + \text{median\_score} \times (1.0 - \text{confidence}) $$

Confidence ranges from 0.3 (0 samples) to 1.0 (100+ samples). The median score itself is adjusted by `MapillaryVisualFriction` (capped between 30 and 75).

---

## Score Interpretation

| Score | Classification | Recommended action |
|---|---|---|
| **76–100** | Lower modelled concern | Monitor; validate with local crash data |
| **51–75** | Moderate risk | Targeted enforcement, limit review, localized calming |
| **26–50** | High concern | Corridor-level review and targeted countermeasures |
| **0–25** | Severe mismatch | Immediate speed-limit and infrastructure intervention |

---

## Reproducibility

All scoring logic is open-source and deterministic:

- Set `MAKENES_DETERMINISTIC=1` to fix ABM random seeds.
- Set `MAKENES_LLM_CACHE=1` to read Board of Evaluator responses from `data/cache/board_evaluations.json`.
- Full audit run: `python prototypes/main.py` (~4.5 hours on 69,966 segments).
- Fast rebuild: `python generate_dashboard.py` (uses SQLite cache + Top 5 ABM replay, ~1 minute).
