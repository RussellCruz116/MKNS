---
name: cross_country_migration
description: "Instructions for migrating the MaKeNeS pipeline to new countries, including dynamic system prompts for the Regional Guides."
---

# Cross-Country Migration Protocol

When scaling MaKeNeS from a developed region (e.g., Thailand, India) to a new country, you MUST employ a **Dynamic System Prompt Generation** step to re-calibrate the Regional Supervisor.

## Dynamic Supervisor Generation

Rather than copying and pasting existing `.md` supervisor files (e.g., `thailand_supervisor.md`), you must generate a new file (e.g., `vietnam_supervisor.md`) using the following logic:

1. **Invoke `intern_research` or `search_web`:**
   Gather the target country's specific demographic and transport data:
   - Primary transport mode (e.g., PTWs, Pedestrians, Cars).
   - Major transport legislation (e.g., Vietnam Road Traffic Law).
   - Existing iRAP or WHO fatalities-per-100k statistics.
   - High-density urban areas vs rural topology.

2. **Generate the Supervisor Markdown:**
   Create a new supervisor file in `agents/supervisors/` using the gathered context. The system prompt (`instructions:` block) must be dynamic.

   **Template for Dynamic System Prompt:**
   ```yaml
   ---
   default_ptw_ratio: [INFERRED_FROM_RESEARCH] # e.g., 0.8 for Vietnam, 0.1 for USA
   risk_tolerance_k: [INFERRED_FROM_WHO_DATA] # e.g., 10.0 for high-risk, 4.0 for low-risk
   ---
   # Instructions
   You are the {Country} Regional Guide. 
   
   Context: In {Country}, the transport landscape is dominated by {Primary_Mode}. 
   Your legal foundation is {Local_Law}.
   
   Directives:
   - When evaluating Speed Safety Scores (S³), explicitly account for the {Primary_Mode} vulnerability.
   - Enforce {Local_Law} penalties if speeds exceed local limits.
   - Align long-term infrastructure goals with the WHO Global Status Report directives for {Country}.
   ```

## Swarm Initialization Hook

When a new country GeoJSON is ingested by the `DataOrchestrator`, the orchestrator automatically detects the geographical boundary using spatial libraries. The agent must intercept this hook to dynamically inject the correct `SubSupervisor` clustering algorithm (e.g., K-Means density proxy).

This ensures the pipeline adapts purely through data and LLM system prompts, requiring zero changes to the underlying Python physics engine.
