import os
import random
import yaml
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skills.environmental_context import EnvironmentalContext
class BoardOfEvaluators:
    """
    A Board of 10 Sub-Agent Assistants. Each assistant has a specific policy domain.
    They evaluate road archetypes and can dynamically adjust S^3 scoring weights 
    (w1_severity, w2_friction, and risk_tolerance_k) to match local contexts.
    
    Identities and modifiers are dynamically loaded from agents/evaluators/*.md
    """
    def __init__(self):
        self.assistants = []
        self._load_evaluators()
        self.env_context = EnvironmentalContext()

    def _load_evaluators(self):
        # We now point to the globally documented skills/board_of_evaluators to ensure localization logic is shared
        evaluators_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'skills', 'board_of_evaluators')
        if not os.path.exists(evaluators_dir):
            print(f"Warning: Evaluators directory {evaluators_dir} not found.")
            return

        for filename in os.listdir(evaluators_dir):
            if filename.endswith('.md'):
                filepath = os.path.join(evaluators_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Extract YAML frontmatter
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            frontmatter = parts[1]
                            params = yaml.safe_load(frontmatter)
                            if params and 'name' in params:
                                self.assistants.append(params)
                except Exception as e:
                    print(f"Failed to load evaluator {filename}: {e}")
                    
        print(f"Board of Evaluators initialized with {len(self.assistants)} markdown agents.")

    def _select_assistant_for_archetype(self, arch_data, inferred_zone):
        """Routes the archetype to the most appropriate specialist on the board."""
        if not self.assistants:
            # Fallback if loading failed
            return {"name": "Fallback Generic Agent", "domain": "General", "k_modifier": 1.0, "w1_mod": 1.0, "w2_mod": 1.0}
            
        def find_assistant(name):
            return next((a for a in self.assistants if a.get("name") == name), None)

        assistant = None
        if "School" in inferred_zone:
            assistant = find_assistant("School Zone Guardian")
        elif "Motorway" in inferred_zone:
            assistant = find_assistant("Motorway Specialist")
        elif "Urban" in inferred_zone or "Market" in inferred_zone:
            assistant = find_assistant("Urban Planner")
        elif arch_data['F85'] > 80:
            assistant = find_assistant("Freight Optimizer")
        elif arch_data['S3_Avg'] < 30:
            assistant = find_assistant("Vision Zero Director")
            
        if not assistant:
            # Randomly assign to a generalist
            generalists = ["VRU Advocate", "Local Commuter", "Public Transit Liaison", "Two-Wheeler Rep"]
            available = [find_assistant(g) for g in generalists if find_assistant(g) is not None]
            if available:
                assistant = random.choice(available)
            else:
                assistant = random.choice(self.assistants)
                
        return assistant

    def evaluate_and_tweak(self, archetypes, base_k=4.0):
        """
        Delegates archetypes to the board. 
        Returns a dictionary mapping Archetype ID -> (Intervention Text, Tweak Dict)
        """
        print(f"[Board of Evaluators] Chairman delegating {len(archetypes)} archetypes to {len(self.assistants)}-Assistant Board...")
        results = {}
        
        for arch_id, data in archetypes.items():
            inferred_zone = data.get('InferredZone', 'Generic Road')
            assistant = self._select_assistant_for_archetype(data, inferred_zone)
            
            # The assistant formulates a localized intervention and mathematical tweaks
            base_intervention = f"[{assistant['name']}] "
            domain = assistant.get('domain', 'general safety')
            
            # Intelligent physics-based analysis of the speed variance
            speed_delta = data['F85'] - data['SpeedLimit']
            variance_context = "F85 significantly exceeds the posted limit." if speed_delta > 0 else "Speed compliance is stable."
            
            # Phase 30: Systemic Non-Compliance Detection and Telemetry Grounding
            percent_over = data.get('PercentOverLimit', 0.0)
            sample_size = data.get('SampleSize_avg', 10.0)
            median_speed = data.get('MedianSpeed', data['F85'])
            
            # Bridge local telemetry to global Safe System rules
            if sample_size > 50 and percent_over > 0.3:
                variance_context += " High-confidence telemetry confirms Systemic Non-Compliance (high rate of speeders). Mandatory Automated Enforcement required."
            elif percent_over > 0.3:
                variance_context += " WARNING: Systemic Non-Compliance (elevated rate of speeders). Evaluate traffic calming."
                
            if median_speed > data['SpeedLimit'] + 10:
                variance_context += " Even the median driver exceeds the safe system limit by >10km/h; the road's geometric design fundamentally encourages speeding."
                
            # Phase 40: Smart Rubric Evaluation
            if 'Score_Kinematics' in data and 'Max_Kinematics' in data:
                kin_loss = data['Max_Kinematics'] - data['Score_Kinematics']
                vru_loss = data['Max_VRU'] - data['Score_VRU']
                if kin_loss > 10.0:
                    variance_context += " Major penalty applied due to lethal kinematic severity."
                if vru_loss > 5.0:
                    variance_context += " High VRU exposure penalty actively dragging down the score."
            
            if "Motorway" in inferred_zone or data['SpeedLimit'] >= 80:
                if speed_delta > 15:
                    base_intervention += f"High speed variance on {inferred_zone}. {variance_context} Align speed limits to natural flow and segregate lanes."
                elif data['S3_Avg'] <= 40:
                    base_intervention += f"Motorway risk detected. Align posted limit to design speed, segregate lanes, and implement automated enforcement."
                else:
                    base_intervention += f"Flow is optimal for motorway safety. Maintain current geometric design."
            else:
                if data['S3_Avg'] <= 30:
                    base_intervention += f"Critical {domain} hazard in {inferred_zone}! {variance_context} Immediate physical traffic calming (e.g. speed bumps, chicanes) required."
                elif data['S3_Avg'] < 70:
                    if speed_delta > 10:
                        base_intervention += f"High kinetic friction threatening {domain}. {variance_context} Implement automated enforcement and optical illusions."
                    else:
                        base_intervention += f"Reduce limits or segregate lanes to protect {domain}."
                else:
                    base_intervention += f"Flow is optimal for {domain}. Maintain current geometric design."

            # Phase 40: Direct ABM influence and distinct conflict types
            avg_hazards = data.get('Avg_EffectiveHazards', 0.0)
            avg_v2v = data.get('Avg_V2V_Conflicts', 0.0)
            avg_v2o = data.get('Avg_V2O_Conflicts', 0.0)
            avg_stress = data.get('Avg_ABM_Stress', 0.0)
            
            # Phase 53: POI and Infrastructure Exposure
            schools_nearby = data.get('POI_Schools_500m', 0)
            crosswalks = data.get('Mapillary_Crosswalks', 0) + data.get('OSM_Crossings_500m', 0)
            sidewalks = data.get('OSM_Sidewalks_500m', 0)
            urban_pop = data.get('UrbanCentre_Pop', 0)
            
            if avg_hazards > 0.5:
                if schools_nearby > 0:
                    base_intervention += f" CRITICAL: Simulated VRU hazard detected near {int(schools_nearby)} school(s). Immediate pedestrian safety enhancements required."
                else:
                    base_intervention += " Simulated VRU hazard detected (High exposure rate). Immediate pedestrian safety enhancements required."
            if avg_v2v > 0.5:
                base_intervention += " High density of Vehicle-to-Vehicle (V2V) conflicts detected. Rear-end hazards demand speed harmonization or lane markings."
            if avg_v2o > 0.5:
                base_intervention += " High Vehicle-to-Obstruction (V2O) risk. Implement clear zones and address visual friction hazards."
                
            # Phase 53: Infrastructure Deficit Triggers
            if urban_pop > 50000 or 'Urban' in inferred_zone:
                if crosswalks == 0 and sidewalks == 0:
                    base_intervention += f" SEVERE INFRASTRUCTURE DEFICIT: Urban area entirely lacks safe pedestrian infrastructure. Install sidewalks and marked crossings immediately."
            if schools_nearby > 0 and sidewalks == 0:
                base_intervention += f" UNACCEPTABLE RISK: School zone lacks dedicated sidewalks. Protect vulnerable children with raised walkways."

            # Apply Environmental Context Skill
            env_data = self.env_context.extract_environmental_risk(data, inferred_zone)
            if env_data['risk_multiplier'] > 1.0:
                env_details = ", ".join(env_data['details'])
                base_intervention += f" [Environmental Hazard Detected: {env_details}]"


            # Calculate tweaked scoring parameters with Guardrails against Weight Inflation
            raw_k = base_k * float(assistant.get('k_modifier', 1.0))
            raw_w1 = float(assistant.get('w1_mod', 1.0))
            raw_w2 = float(assistant.get('w2_mod', 1.0))
            
            # Guardrail 1: Cap the sigmoid steepness (k) so the model doesn't become a rigid step function
            max_allowed_k = base_k * 1.5
            k_tweaked = min(raw_k, max_allowed_k)
            k_tweaked = max(k_tweaked, 1.0) # Prevent k from dropping to 0 or negative
            
            # Guardrail 2: Normalize w1 and w2 to prevent penalty inflation
            total_w_mod = raw_w1 + raw_w2
            if total_w_mod == 0:
                total_w_mod = 1.0
                raw_w1, raw_w2 = 1.0, 1.0
                
            # Phase 35: Give AI Agents a direct say as a reviewer on the final score.
            ai_score_adjustment = 0.0
            if data['S3_Avg'] <= 30:
                ai_score_adjustment = -15.0 # Increased from -10
            elif data['S3_Avg'] < 70 and speed_delta > 10:
                ai_score_adjustment = -10.0 # Increased from -5
            elif data['S3_Avg'] >= 70 and speed_delta <= 5:
                ai_score_adjustment = 10.0 # Increased reward
                
            # Phase 40: ABM directly subtracts points via AI evaluation based on all types
            if avg_hazards > 0.0:
                ai_score_adjustment -= (avg_hazards * 5.0) # Up to 10 point penalty for severe VRU hazards
            if avg_v2v > 0.0:
                ai_score_adjustment -= (avg_v2v * 3.0) # Penalize rear-ends harder
            if avg_v2o > 0.0:
                ai_score_adjustment -= (avg_v2o * 3.0) # Penalize runoff/infrastructure strikes harder
            if avg_stress > 0.0:
                ai_score_adjustment -= (avg_stress * 2.0)
                
            # Increase penalty based on environmental risk
            env_penalty = (env_data['risk_multiplier'] - 1.0) * 10.0
            ai_score_adjustment -= env_penalty
            
            # Remove the rigid cap to allow natural variance based on exact ABM stress
            # ai_score_adjustment = max(-25.0, min(25.0, ai_score_adjustment))
                
            tweaks = {
                'k_tweaked': k_tweaked,
                'w1_tweaked': 0.5 * (raw_w1 / (total_w_mod / 2.0)), # Normalize relative to default 1.0 sum
                'w2_tweaked': 0.5 * (raw_w2 / (total_w_mod / 2.0)),
                'ai_score_adjustment': ai_score_adjustment
            }
            
            results[arch_id] = {
                'intervention': base_intervention,
                'tweaks': tweaks,
                'assistant': assistant['name']
            }
            
        # Phase 42: Use GenAI wisely (batched) to generate dynamic systemic rationales
        try:
            import os
            from google import genai
            from google.genai import types
            import json
            from prototypes.reproducibility import (
                archetype_cache_key,
                load_llm_cache,
                save_llm_cache,
            )
            
            api_key = os.environ.get("GEMINI_API_KEY")
            if api_key and len(results) > 0:
                cache_key = archetype_cache_key({k: v['intervention'] for k, v in results.items()})
                cached = load_llm_cache(cache_key)
                if cached:
                    print(f"[Board of Evaluators] Using cached LLM evaluations ({cache_key}).")
                    genai_outputs = cached
                else:
                    print(f"[Board of Evaluators] Requesting GenAI dynamic rationales for {len(results)} archetypes...")
                    client = genai.Client(api_key=api_key)

                    prompt = (
                        "You are a Board of Evaluators for a road safety digital twin.\n"
                        "For each road archetype (which are now mathematically discovered empirical PCA clusters), provide a 1-2 sentence systemic policy intervention AND a final mathematical score adjustment (-15.0 to +15.0).\n"
                        "Use the provided PCA cluster characteristics to base your penalties (for hazards) or bonuses (for safety). These clusters represent true latent risk groups.\n\n"
                    )

                    for arch_id, res in results.items():
                        prompt += f"Archetype {arch_id} | Assistant: {res['assistant']} | Context: {res['intervention']}\n"

                    schema = types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            str(arch_id): types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "policy_intervention": types.Schema(type=types.Type.STRING),
                                    "score_adjustment": types.Schema(type=types.Type.NUMBER)
                                }
                            ) for arch_id in results.keys()
                        }
                    )

                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=schema,
                        )
                    )

                    genai_outputs = json.loads(response.text)
                    save_llm_cache(cache_key, genai_outputs)

                for arch_id, gen_obj in genai_outputs.items():
                    key = int(arch_id) if arch_id.isdigit() else arch_id
                    target = key if key in results else (arch_id if arch_id in results else None)
                    if target is not None:
                        # Append the LLM specific insight to the base mathematical context
                        results[target]['intervention'] = f"{results[target]['intervention']} [AI Insight: {gen_obj.get('policy_intervention', '')}]"
                        # Apply GenAI direct score adjustment, replacing the hardcoded heuristic
                        results[target]['tweaks']['ai_score_adjustment'] = float(gen_obj.get('score_adjustment', 0.0))
                        
        except Exception as e:
            print(f"[Board of Evaluators] GenAI augmentation skipped or failed: {e}")
            pass
            
        return results
