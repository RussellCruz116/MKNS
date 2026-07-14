---
domain: Rural Roads
k_modifier: 0.9
name: Rural Highway Patrol
w1_mod: 1.2
w2_mod: 0.9
---

# Rural Highway Patrol

**Focus:** Preventing high-speed run-off-road and head-on crashes on undivided rural roads.

## Policy Grounding

### 1. Global Policy
iRAP - Audio-tactile edge lines and centerline rumble strips.

### 2. Regional Policy (Asia-Pacific)
ADB Rural Road Safety Action Plans.

### 3. Local Policy Alignment
National standards for rural road geometry and clear zones.

## Scoring Configuration Limits
- **w1_mod_bounds**: [0.8, 1.2]
- **w2_mod_bounds**: [0.8, 1.2]
- **k_modifier_max**: 1.5

*Note: Weight modifications must represent a trade-off. Extreme inflation is monitored.*

# Direct Mathematical Scoring
As a GenAI Evaluator, you now have direct control over the Speed Safety Score. You MUST output a score_adjustment parameter between -15.0 and +15.0. Provide harsh negative penalties for severe kinematic or VRU hazards, and positive bonuses for perfectly aligned Safe System roads.
