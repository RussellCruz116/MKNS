---
name: evaluator_policy_grounding
description: "Guidelines and instructions for tying MaKeNeS Evaluators to Global, Regional, and Local Road Safety Policies."
---

# Evaluator Policy Grounding Skill

This skill enforces that the decisions and scoring modifications (`w1`, `w2`, `k`) proposed by the MaKeNeS `BoardOfEvaluators` must be grounded in established road safety laws, policies, and frameworks. This grounds the generative agents in objective reality and protects the simulation from "weight inflation" or hallucinated interventions.

## Multi-Tiered Policy Framework

Whenever generating or updating an Evaluator Agent (e.g., `School Zone Guardian`, `Vision Zero Director`), the prompt/instructions MUST adhere to the following three tiers of policy alignment:

### 1. Global Policies (WHO / iRAP)
**Source:** World Health Organization (WHO) Global Status Report on Road Safety; International Road Assessment Programme (iRAP) Star Ratings.
- **Rule:** The universal baseline for survivability.
- **Example Intervention:** "Under WHO Global guidelines, vulnerable road users cannot survive impacts above 30 km/h. Recommend traffic calming to enforce this physical limit."

### 2. Regional Policies (ADB / GRSF)
**Source:** Asian Development Bank (ADB) Transport Sector Guidelines; Global Road Safety Facility (GRSF).
- **Rule:** Acknowledges the specific characteristics of the region (e.g., high presence of Powered Two-Wheelers in the Asia-Pacific region).
- **Example Intervention:** "Following ADB Regional guidelines for high PTW density, recommend physically segregated two-wheeler lanes rather than just speed reduction."

### 3. Local Policies (National Laws)
**Source:** Country-specific legislative acts (e.g., Thailand's Land Traffic Act, India's Motor Vehicles Amendment Act).
- **Rule:** Ensures the intervention is legally recognizable by the local transport ministry.
- **Example Intervention:** "In accordance with the Motor Vehicles Amendment Act, strict enforcement cameras are required on this high-speed arterial."

## Implementation Guardrails

To prevent "weight inflation" (where agents aggressively boost their priority domains to the point of breaking the simulation):

1. **`w1_mod` and `w2_mod`:** Must represent a *trade-off*. If an evaluator prioritizes Kinematic Severity (`w1_mod` > 1.0), it MUST de-prioritize Contextual Friction (`w2_mod` < 1.0) and vice versa. 
2. **`k_modifier`:** Represents the steepness of the Safe System penalty curve. Maximum allowable `k_modifier` should not exceed `1.5`, ensuring the Sigmoid function does not become an unreadable binary step-function.
3. **Citations:** Evaluator markdown files must explicitly cite the framework (e.g., "WHO 30km/h limit") in their `policy_foundation` or `rules` section.

## Adaptability
When migrating to new datasets (e.g., migrating from Thailand to a new country like Vietnam), the local policy definitions in the Evaluator markdown files must be dynamically updated to reflect the new local laws (e.g., Vietnam's Road Traffic Law). The Global and Regional frameworks remain constant.
