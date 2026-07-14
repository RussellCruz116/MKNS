import geopandas as gpd
import pandas as pd
import os
import yaml
import re

class AgenticSupervisor:
    """
    Agentic Supervisor class. It parses a Markdown file from agents/supervisors/
    to configure its physics assumptions (YAML frontmatter) and loads the LLM
    persona prompt directly from the file content to direct its speed interventions.
    """

    def __init__(self, agent_markdown_path, data_path=None, network_gdf=None):
        if not os.path.exists(agent_markdown_path):
            raise FileNotFoundError(f"Agent definition not found: {agent_markdown_path}")
            
        self.data_path = data_path
        self.network = network_gdf
        
        # Parse Markdown Agent Definition
        with open(agent_markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract YAML frontmatter
        self.params = {}
        match = re.match(r'^-{3}\n(.*?)\n-{3}\n(.*)', content, re.DOTALL)
        if match:
            yaml_content = match.group(1)
            self.persona_prompt = match.group(2).strip()
            self.params = yaml.safe_load(yaml_content) or {}
        else:
            self.persona_prompt = content.strip()
            
        self.name = self.params.get('name', 'Generic Supervisor')
        self.default_ptw_ratio = self.params.get('ptw_ratio', self.params.get('default_ptw_ratio', 0.5))
        self.mobil_politeness = self.params.get('mobil_politeness', 0.2)
        self.sfm_repulsion_strength = self.params.get('sfm_repulsion_strength', 2.0)

    def load_network(self):
        """Loads the GeoJSON or GPKG network using GeoPandas, or uses the injected GDF."""
        if self.network is None:
            if not os.path.exists(self.data_path):
                raise FileNotFoundError(f"Data file not found at {self.data_path}")
            
            self.network = gpd.read_file(self.data_path)
            
        print(f"[{self.name}] Loaded network with {len(self.network)} segments.")
        self._apply_regional_rules()
        return self.network

    def _apply_regional_rules(self):
        """
        Applies logic injected from the agent parameters.
        """
        if 'SpeedLimit' in self.network.columns:
            self.network['SpeedLimit'] = self.network['SpeedLimit'].fillna(50)
        else:
            self.network['SpeedLimit'] = 50
        
        self.network['SpeedLimit'] = pd.to_numeric(self.network['SpeedLimit'], errors='coerce').fillna(50)

        if 'F85thPercentileSpeed' not in self.network.columns:
            self.network['F85thPercentileSpeed'] = self.network['SpeedLimit'] * 1.1 
            
        # Agent physics context overrides
        self.network['mobil_politeness'] = self.mobil_politeness
        self.network['sfm_repulsion_strength'] = self.sfm_repulsion_strength
        
        return self.network

    def evaluate_archetype_interventions(self, archetypes, swarm_metrics=None):
        """
        Takes a list/dict of unique road archetypes and asks the LLM for a policy intervention,
        instructed specifically by the agent's markdown persona.
        """
        prompt = f"{self.persona_prompt}\n\n"
        
        if swarm_metrics:
            prompt += f"--- SYNTHETIC SWARM PHYSICS TELEMETRY ---\n"
            prompt += f"Total Sub-Lane TTC Conflicts (<1.5s): {swarm_metrics['total_TTC_conflicts']}\n"
            prompt += f"Total Post-Encroachment Hazards (PET): {swarm_metrics['total_PET_hazards']}\n"
            prompt += f"Global VRU Exposure Factor: {swarm_metrics['vru_exposure_factor']:.2f}\n"
            prompt += f"-----------------------------------------\n\n"
            
        prompt += (
            "CRITICAL CONTEXT FOR AI SUPERVISOR:\n"
            "You are evaluating 'Archetypes', which represent CLUSTERS of similar road SEGMENTS across an entire regional AREA.\n"
            "Do NOT recommend interventions that only apply to a single intersection or single street.\n"
            "Instead, provide systemic, area-wide policy recommendations that apply to the entire cluster of segments (e.g., 'mandate segregated bike lanes for all 50km/h urban arterials', 'deploy automated speed enforcement corridors').\n\n"
            "Additionally, you must evaluate the project from both a BUSINESS perspective (economic impact, commerce efficiency, logistical flow) and a GOVERNMENT perspective (public safety, policy alignment, budget efficiency).\n\n"
            "For the following clustered road archetypes within this sub-network, provide your systemic policy evaluation:\n\n"
        )
        
        for arch_id, data in archetypes.items():
            prompt += f"Archetype: {arch_id} | Limit: {data['SpeedLimit']} | 85th Pct: {data['F85']} | Avg S3 Score: {data['S3_Avg']}\n"
            
        interventions = {}
        try:
            from google import genai
            from google.genai import types
            import json
            
            api_key = os.environ.get("GEMINI_API_KEY")
            if api_key:
                client = genai.Client(api_key=api_key)
                
                # Define structured output schema to prevent hallucinated formats
                schema = types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        str(arch_id): types.Schema(type=types.Type.STRING) for arch_id in archetypes.keys()
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
                
                interventions_raw = json.loads(response.text)
                # Clean up keys if necessary
                for k, v in interventions_raw.items():
                    interventions[str(k)] = v
        except Exception as e:
            print(f"[{self.name}] Agent LLM Evaluation failed: {e}")
            pass
            
        for arch_id, data in archetypes.items():
            arch_str = str(arch_id)
            if arch_str not in interventions and arch_id not in interventions:
                if data['S3_Avg'] < 40:
                    interventions[arch_id] = "CRITICAL: Urgent traffic calming and limit reduction required."
                elif data['S3_Avg'] < 70:
                    interventions[arch_id] = "Lower speed limit and protect VRU crossings."
                else:
                    interventions[arch_id] = "No intervention needed."
                    
        return interventions
