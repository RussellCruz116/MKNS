# Update 1.2 — Network-Aware ABM, Hybrid Scoring, and Pipeline Hardening

## Background

Update 1.1 corrected the scoring system from relative rank-based to absolute physics-based, and deployed the full 69,966-segment network. The user identified two remaining issues:
1. **ABM actors are not spread out** in the video replay — traced to micro-segments being selected for Top-5.
2. **ABM is segment-isolated** — actors live and die on a single segment, with no awareness of how segments connect, intersect, or feed traffic into each other.

Additionally, the scoring calibration needs to combine power-law with skewnorm (not replace one with the other) to avoid pushing too many roads to "bad."

---

## Network Topology Discovery

From analyzing the GeoJSON geometry endpoints (20-segment sample → extrapolated to 69,966):

| Metric | Value |
|--------|-------|
| Geometry type | All `LineString` |
| Shared junction nodes (degree ≥ 2) | 11 of 26 in sample (~42%) |
| Reverse pairs detected | Segments 1↔2 share identical endpoints reversed |
| `oneway` column | ❌ Not in dataset |
| `OSM_LaneCount` column | ✅ Available |
| Node-sharing pattern | Start/end coordinate snapping at 5 decimal places (~1.1m) |

**Key finding:** The network already encodes topology implicitly through shared LineString endpoints. Two segments sharing a start/end node are connected at a junction. A reverse pair (A→B and B→A) represents a two-way road with separate directional segments.

---

## Proposed Changes

### 1. Network Topology Engine — New Module

#### [NEW] [network_topology.py](file:///C:/Users/Johan/OneDrive/Documents/ADB/makenes_project/prototypes/analytical_model/network_topology.py)

A pre-processing module that builds a graph from the GeoJSON geometry, run **once** before the ABM:

```python
class NetworkTopology:
    """
    Builds a segment adjacency graph from shared LineString endpoints.
    Infers flow direction (one-way vs two-way) from reverse-pair detection.
    Provides junction metadata (degree, intersection type).
    """
    
    def __init__(self, gdf, precision=5):
        self.gdf = gdf
        self.precision = precision  # ~1.1m snapping
        
        # Core data structures
        self.node_index = {}       # (lon,lat) -> [(oid, 'start'|'end'), ...]
        self.adjacency = {}        # oid -> set(neighbor_oids)
        self.segment_nodes = {}    # oid -> (start_node, end_node)
        self.reverse_pairs = {}    # oid -> paired_oid (bidirectional)
        self.junction_degree = {}  # (lon,lat) -> int
        self.is_one_way = {}       # oid -> bool
        
        self._build()
    
    def _build(self):
        # Phase 1: Index all segment endpoints
        # Phase 2: Build adjacency from shared nodes (O(n) amortized via dict)
        # Phase 3: Detect reverse pairs via endpoint-swap matching (O(n) via dict)
        # Phase 4: Infer one-way: unpaired segments = one-way
        # Phase 5: Classify junctions by degree:
        #   - degree 1 = dead end
        #   - degree 2 = continuation
        #   - degree 3 = T-junction
        #   - degree 4+ = intersection / roundabout
        pass
    
    def get_neighbors(self, oid):
        """Returns set of segment OIDs connected to this segment."""
        
    def get_junction_at(self, oid, end='end'):
        """Returns junction metadata where this segment terminates."""
        
    def is_two_way(self, oid):
        """True if this segment has a reverse-direction counterpart."""
        
    def get_reverse_pair(self, oid):
        """Returns the OBJECTID of the reverse-direction segment, or None."""
        
    def get_flow_direction(self, oid):
        """Returns 'one_way' | 'two_way' | 'unknown'."""
        
    def get_upstream_segments(self, oid):
        """Segments that feed traffic INTO this segment's start node."""
        
    def get_downstream_segments(self, oid):
        """Segments that receive traffic FROM this segment's end node."""
```

**Reverse-pair detection** uses an O(n) hash approach (not O(n²)):
```python
# Build dict: (start, end) -> oid
endpoint_map = {}
for oid, (s, e) in segment_nodes.items():
    endpoint_map[(s, e)] = oid

# Detect pairs: check if (end, start) exists
for oid, (s, e) in segment_nodes.items():
    reverse_key = (e, s)
    if reverse_key in endpoint_map:
        partner = endpoint_map[reverse_key]
        if partner != oid:
            reverse_pairs[oid] = partner
            reverse_pairs[partner] = oid
```

---

### 2. ABM Engine — Network-Aware Actor Flow

#### [MODIFY] [abm_engine.py](file:///C:/Users/Johan/OneDrive/Documents/ADB/makenes_project/prototypes/analytical_model/abm_engine.py)

Current state: Each segment is an isolated micro-world. Actors wrap around within their own segment. Direction is randomly assigned (60/40 split).

**Changes:**

##### 2a. Accept `NetworkTopology` in constructor
```python
class MaKeNeSABM(mesa.Model):
    def __init__(self, regional_network, topology=None, ptw_ratio=0.65, ...):
        self.topology = topology  # NetworkTopology instance
```

##### 2b. Flow-aware direction assignment
Instead of `direction = 1.0 if random.random() < 0.6 else -1.0`:
```python
if self.topology and self.topology.is_one_way(seg_id):
    direction = 1.0  # All traffic flows in the digitized direction
elif self.topology and self.topology.is_two_way(seg_id):
    direction = 1.0 if random.random() < 0.5 else -1.0  # 50/50 for two-way
else:
    direction = 1.0 if random.random() < 0.6 else -1.0  # Fallback
```

##### 2c. Cross-segment actor handoff at boundaries
When an actor reaches the end of its segment (distance_traveled ≥ line_geom.length), instead of wrapping around, the actor can **transfer to a downstream segment**:

```python
# In BaseActor.step(), replace wrap-around logic:
if self.distance_traveled >= self.line_geom.length:
    if self.model.topology:
        downstream = self.model.topology.get_downstream_segments(self.segment_id)
        if downstream:
            # Pick a downstream segment (weighted by road class priority)
            next_seg_id = random.choice(list(downstream))
            next_seg_data = self.model.segment_data.get(next_seg_id)
            if next_seg_data:
                self.segment_id = next_seg_id
                self.line_geom = next_seg_data['geometry']
                self.distance_traveled = 0.0
                self.geometry = self.line_geom.interpolate(0.0)
                return
    # Fallback: wrap around
    self.distance_traveled -= self.line_geom.length
```

> [!IMPORTANT]
> Cross-segment handoff only applies to the **Top-5 replay segments and their immediate neighbors** (1-hop adjacency). For the full 69,966-segment pipeline, actors still wrap within their segment to avoid O(n²) memory explosion. The topology graph is used globally only for junction-aware scoring penalties (see §4).

##### 2d. Junction conflict detection
At junctions (degree ≥ 3), actors from different segments approaching the same node create **intersection conflicts**:

```python
# In step(), after per-segment processing:
if self.topology:
    for node, segments in self.topology.junction_segments.items():
        if len(segments) < 3: continue  # Skip non-intersections
        junction_actors = []
        for sid in segments:
            junction_actors.extend([a for a in segment_map.get(sid, [])
                                    if a.actor_type in ['Car', 'PTW', 'HGV']
                                    and self._near_junction(a, node)])
        # Check all pairs for TTC at junction
        for i, a in enumerate(junction_actors):
            for b in junction_actors[i+1:]:
                ttc = self.calculate_ttc(a, b)
                if ttc < 5.0:
                    self.conflict_logs.append({
                        'type': 'JUNCTION',
                        'segment_ids': [a.segment_id, b.segment_id],
                        ...
                    })
```

---

### 3. Scoring Calibration — Hybrid Power-Law + SkewNorm

#### [MODIFY] [backfill_scoring.py](file:///C:/Users/Johan/OneDrive/Documents/ADB/makenes_project/scripts/backfill_scoring.py)

**Approach:** Apply both calibrations side-by-side and blend them, rather than choosing one:

```python
from scipy.stats import skewnorm

raw_total = gdf[SCORE_COLUMNS + ["Score_Infrastructure"]].sum(axis=1).clip(0.0, 100.0)
gdf["SpeedSafetyScore_PreShipRaw"] = raw_total

# --- Channel A: Power-law stretch (preserves absolute physics meaning) ---
power_score = (raw_total / 100.0) ** 1.15 * 100.0

# --- Channel B: Skewnorm (provides relative context within the distribution) ---
rank_pct = raw_total.rank(method="first", pct=True).clip(0.0001, 0.9999)
skewed_vals = skewnorm.ppf(rank_pct, a=-3.0)  # Lighter skew than before (-3 vs -4)
s_min, s_max = skewed_vals.min(), skewed_vals.max()
if s_max > s_min:
    skew_score = 0.2 + (100.0 - 0.2) * (skewed_vals - s_min) / (s_max - s_min)
else:
    skew_score = raw_total

# --- Blend: 70% power-law (physics-dominant) + 30% skewnorm (distribution-aware) ---
BLEND_PHYSICS = 0.70
BLEND_RELATIVE = 0.30
gdf["SpeedSafetyScore"] = (power_score * BLEND_PHYSICS + skew_score * BLEND_RELATIVE).clip(0.0, 100.0)

gdf["ScoreCalibration"] = "Hybrid_PL1.15_SN-3.0_70-30"
```

**Why this blend:**
- The power-law (70%) preserves the absolute physical meaning — a score of 10 means a genuinely hazardous road, not just "bottom 10% relative to peers."
- The skewnorm (30%) adds distribution awareness — it prevents the situation where a cluster of roads that are all genuinely dangerous (e.g., raw scores 15-25) get mapped to nearly identical calibrated scores. The skewnorm gently spreads them so the *worst* among the bad still stands out.
- The lighter skew (α = -3.0 vs old -4.0) avoids the original problem where the skewnorm dominated and made everything look decent.

**Both channels will be saved to the GeoJSON** as `Score_PowerLaw` and `Score_SkewNorm` for transparency, alongside the blended `SpeedSafetyScore`.

---

### 4. ABM Actor Spread Fix — Smart Replay Selection

#### [MODIFY] [generate_chunked_dashboard.py](file:///C:/Users/Johan/OneDrive/Documents/ADB/makenes_project/scripts/generate_chunked_dashboard.py)

**Problem:** Top-5 selection picks segments as short as 14m.

**Fix at line ~2062:**
```python
# Filter replay candidates to visually meaningful segments (>= 200m)
MIN_REPLAY_LENGTH_M = 200.0
gdf_copy['geom_length_m'] = gdf_copy.geometry.length * 111320.0
replay_candidates = gdf_copy[gdf_copy['geom_length_m'] >= MIN_REPLAY_LENGTH_M]
top_5_sids = replay_candidates.sort_values(by='SpeedSafetyScore', ascending=True).head(5)['OBJECTID'].values
```

**For the replay ABM**, also load the 1-hop neighbor segments from the topology graph so actors can flow across segment boundaries in the video:
```python
if topology:
    neighbor_sids = set()
    for sid in top_5_sids:
        neighbor_sids.update(topology.get_neighbors(sid))
    replay_segments = gdf_copy[gdf_copy['OBJECTID'].isin(set(top_5_sids) | neighbor_sids)]
else:
    replay_segments = top_5_segments
```

---

### 5. Step Count

Increase simulation steps from 300 → **600** for the Top-5 replay ABM.

In `generate_chunked_dashboard.py`:
```python
_, _, _, frame_logs = abm.run_simulation(steps=600, region_id="chunked_dashboard")
```

In `abm_engine.py`, sample every 2nd step for frame recording to keep `frame_data.json` at a manageable size:
```python
# Record frame only on even steps
if len(self.frame_logs) < 3000 and step_num % 2 == 0:
    ...
```

For the full pipeline (`prototypes/main.py`), keep 300 steps to avoid doubling runtime across all 34 clusters.

---

### 6. Chunking Hardening

#### [MODIFY] [generate_chunked_dashboard.py](file:///C:/Users/Johan/OneDrive/Documents/ADB/makenes_project/scripts/generate_chunked_dashboard.py)

Invoke chunking directly after writing the optimized GeoJSON, then delete the monolithic file:

```python
# After gdf_opt.to_file(output_path, driver="GeoJSON")
from scripts.setup_ghpages import split_geojson
chunks = split_geojson(str(output_path))
output_path.unlink()  # Remove the >100MB file
```

Also ensure `.gitignore` contains:
```
docs/makenes_scored_optimized.geojson
docs/makenes_scored_conflicts.geojson
```

---

### 7. Supervisor & Evaluator Notes

> [!NOTE]
> The Board of Evaluators ([board_of_evaluators.py](file:///C:/Users/Johan/OneDrive/Documents/ADB/makenes_project/agents/board_of_evaluators.py)) and supervisor hierarchy ([supervisors/](file:///C:/Users/Johan/OneDrive/Documents/ADB/makenes_project/agents/supervisors)) are already integrated into the scoring pipeline via `score_calculator.py`. They dynamically adjust rubric weights based on road archetype routing (School Zone Guardian, Motorway Specialist, VRU Advocate, etc.).
> 
> **For Update 1.2**, the evaluators benefit indirectly from the network-aware ABM because the conflict logs they receive will now include `JUNCTION` type conflicts and topology-aware flow data, improving their ability to assess intersection risk contexts.
>
> No structural changes are needed to the evaluator/supervisor code itself.

---

## Summary of Deliverables

| Component | Change | Impact |
|-----------|--------|--------|
| `network_topology.py` | **[NEW]** Segment graph, junction classification, one-way/two-way inference, reverse-pair detection | Foundation for all network-aware features |
| `abm_engine.py` | Flow-aware direction, cross-segment handoff (replay only), junction conflict detection | Actors behave like real traffic |
| `backfill_scoring.py` | Hybrid 70/30 power-law + skewnorm blend | Balanced calibration: physics-grounded + distribution-aware |
| `generate_chunked_dashboard.py` | ≥200m replay filter, neighbor loading, 600 steps, inline chunking | Better replays, no push failures |
| `prototypes/main.py` | Pass `NetworkTopology` to ABM | Enable topology-aware simulation globally |

---

## Verification Plan

### Automated Tests
1. Run `_analyze_topology.py` on full dataset and verify:
   - Reverse pairs detected > 20,000 (expecting ~30,000 from 69,966 segments)
   - Intersections (degree ≥ 3) detected > 5,000
2. Run `backfill_scoring.py` and verify new score distribution:
   - Min < 3, Median ~48-55, Max = 100
   - `Score_PowerLaw` and `Score_SkewNorm` columns both present
3. Run `generate_chunked_dashboard.py` and verify:
   - All 5 replay segments ≥ 200m
   - Frame data shows actors moving across segment boundaries
   - All chunks < 50MB
4. `git push` succeeds without LFS errors

### Manual Verification
- Play 2+ ABM replays: actors should spread along corridors, visually enter/exit at segment ends
- Map color ramp: worst roads should be clearly red, moderate roads yellow, safe roads green
- What-If toggle: verify color changes
