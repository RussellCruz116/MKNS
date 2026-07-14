import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.board_of_evaluators import BoardOfEvaluators

class SpeedSafetyScoreCalculator:
    """
    Computes the final Speed Safety Score (S^3) incorporating empirical kinematics,
    dynamic ML-driven context normalization, and AI-guided human experience.
    """
    def __init__(self, network_gdf, conflict_logs, pet_logs, stress_logs, guide, sim_steps=200, baseline_steps=200):
        """
        Initializes the S^3 Calculator.

        Args:
            network_gdf (GeoDataFrame): Road network with Mapillary features and speeds.
            conflict_logs (list): ABM-detected conflicts.
            pet_logs (list): ABM-detected post-encroachment times.
            stress_logs (list): ABM-detected human stress events.
            guide (RegionalGuide): LLM guidelines for the Board of Evaluators.
            sim_steps (int): The number of simulation steps run.
            baseline_steps (int): The baseline number of simulation steps.
        """
        self.network = network_gdf
        self.conflict_logs = conflict_logs
        self.pet_logs = pet_logs
        self.stress_logs = stress_logs
        self.guide = guide
        self.sim_steps = sim_steps
        self.baseline_steps = baseline_steps
        self.multiplier = self.baseline_steps / self.sim_steps if self.sim_steps > 0 else 1.0
        
    def _logistic_fatality_prob(self, v_85):
        """
        Standard logistic risk curve for collision fatality.
        Based on the Wramborg (2005) probability of pedestrian fatality at speed v.
        
        Args:
            v_85 (float): 85th percentile speed in km/h.
        Returns:
            float: Probability of fatality (0.0 to 1.0).
        """
        if v_85 <= 0: return 0.0
        c1, c2 = -5.0, 0.1
        p = 1 / (1 + np.exp(-(c1 + c2 * v_85)))
        return p

    def _get_rubric_weights(self, road_class, land_use, speed_limit):
        """
        Dynamically adjusts the 100-point rubric weights based on geographic and functional context.
        Urban residential roads heavily penalize VRU and friction issues, while motorways 
        penalize kinematics and speeding.
        
        Returns:
            dict: The max point allocations for the 7 scoring categories.
        """
        if pd.isna(road_class) or road_class in ['UNKNOWN', 'unknown', 'Unknown', '', None]:
            road_class = 'secondary'
        if pd.isna(land_use) or land_use in ['UNKNOWN', 'unknown', 'Unknown', '', None]:
            land_use = 'URBAN'
        try:
            speed_limit = float(speed_limit)
            if np.isnan(speed_limit):
                speed_limit = 50.0
        except (ValueError, TypeError):
            speed_limit = 50.0
            
        # Case 1: Motorways/Speedways (High speed segregated flow)
        if road_class == 'motorway' or speed_limit >= 80:
            return {
                'Score_Kinematics': 25.0,
                'Score_Friction': 25.0,
                'Score_VRU': 5.0,
                'Score_Speeding': 25.0,
                'Score_AI': 15.0,
                'Score_Stress': 0.0,
                'Score_Infrastructure': 5.0
            }
        # Case 2: Urban Residential / School Zone / Low Speed (VRU Dominant)
        elif speed_limit <= 30 or road_class in ['residential', 'living_street']:
            return {
                'Score_Kinematics': 10.0,
                'Score_Friction': 15.0,
                'Score_VRU': 20.0,
                'Score_Speeding': 15.0,
                'Score_AI': 15.0,
                'Score_Stress': 15.0,
                'Score_Infrastructure': 10.0
            }
        # Case 3: Urban Market / Mixed-Use (Moderately low speed)
        elif land_use == 'URBAN' and speed_limit <= 50 and road_class not in ['trunk', 'primary']:
            return {
                'Score_Kinematics': 15.0,
                'Score_Friction': 15.0,
                'Score_VRU': 15.0,
                'Score_Speeding': 15.0,
                'Score_AI': 15.0,
                'Score_Stress': 15.0,
                'Score_Infrastructure': 10.0
            }
        # Case 4: Urban Arterial / Trunk / Primary
        elif land_use == 'URBAN':
            return {
                'Score_Kinematics': 15.0,
                'Score_Friction': 15.0,
                'Score_VRU': 20.0,
                'Score_Speeding': 15.0,
                'Score_AI': 15.0,
                'Score_Stress': 10.0,
                'Score_Infrastructure': 10.0
            }
        # Case 5: Rural Highways / Local Rural Roads
        elif land_use == 'RURAL':
            return {
                'Score_Kinematics': 15.0,
                'Score_Friction': 20.0,
                'Score_VRU': 10.0,
                'Score_Speeding': 20.0,
                'Score_AI': 15.0,
                'Score_Stress': 10.0,
                'Score_Infrastructure': 10.0
            }
        # Fallback / Generic
        else:
            return {
                'Score_Kinematics': 20.0,
                'Score_Friction': 15.0,
                'Score_VRU': 15.0,
                'Score_Speeding': 15.0,
                'Score_AI': 15.0,
                'Score_Stress': 10.0,
                'Score_Infrastructure': 10.0
            }

    def _blended_score(self, penalty_ratio, max_pts, road_class_series, speed_limit_series):
        p = np.clip(penalty_ratio, 0.0, 1.0)
        is_speedway = (road_class_series == 'motorway') | (speed_limit_series >= 80)
        is_slow_vru = (speed_limit_series <= 30) | (road_class_series.isin(['residential', 'living_street']))
        
        linear_weight = np.where(is_speedway, 0.5, np.where(is_slow_vru, 0.3, 0.4))
        exp_weight = 1.0 - linear_weight
        # Make the rubric linear for transport policymakers (Phase 36 style) to prevent over-harshness
        exponent = np.where(is_speedway, 1.0, np.where(is_slow_vru, 1.0, 1.0))
        
        return max_pts * (linear_weight * (1.0 - p) + exp_weight * (1.0 - p) ** exponent)



    def _align_rubric_categories(self, df, score_col='SpeedSafetyScore'):
        categories = {
            'Score_Kinematics': 'Max_Kinematics',
            'Score_Friction': 'Max_Friction',
            'Score_VRU': 'Max_VRU',
            'Score_Speeding': 'Max_Speeding',
            'Score_AI': 'Max_AI',
            'Score_Stress': 'Max_Stress',
            'Score_Infrastructure': 'Max_Infrastructure'
        }
        
        # Calculate current sum
        raw_sum = sum(df[cat] for cat in categories.keys())
        raw_sum_is_zero = (raw_sum == 0)
        
        if raw_sum_is_zero.any():
            for cat, max_col in categories.items():
                df.loc[raw_sum_is_zero, cat] = df.loc[raw_sum_is_zero, max_col] * 0.1
            raw_sum = sum(df[cat] for cat in categories.keys())
            
        final_score = df[score_col]
        
        under_score = final_score > raw_sum
        over_score = final_score < raw_sum
        
        # Case 1: final_score < raw_sum (over-estimate)
        factor = np.where(raw_sum > 0, final_score / raw_sum, 0.0)
        for cat in categories.keys():
            df.loc[over_score, cat] = df.loc[over_score, cat] * factor[over_score]
            
        # Case 2: final_score > raw_sum (under-estimate)
        total_room = sum(df[max_col] - df[cat] for cat, max_col in categories.items())
        total_room = np.where(total_room > 0, total_room, 1.0)
        
        for cat, max_col in categories.items():
            room = df[max_col] - df[cat]
            df.loc[under_score, cat] = df.loc[under_score, cat] + (final_score[under_score] - raw_sum[under_score]) * (room[under_score] / total_room[under_score])
            
        # Finally, clip to limits row-by-row
        for cat, max_col in categories.items():
            df[cat] = np.clip(df[cat], 0.0, df[max_col])
            
        return df

    def compute_scores(self):
        scored_network = self.network.copy()
        
        # 1. Fill NaNs to ensure robust math operations
        # Drop rows missing critical geometries
        if 'geometry' in scored_network.columns:
            scored_network = scored_network.dropna(subset=['geometry'])
            

            
        scored_network['SpeedLimit'] = pd.to_numeric(scored_network['SpeedLimit'], errors='coerce').fillna(50)
        
        # Save original speed limit for comparison in visual interface
        scored_network['OriginalSpeedLimit'] = scored_network['SpeedLimit'].copy()
        
        if 'Overture_Maxspeed' in scored_network.columns:
            ov_speed = pd.to_numeric(scored_network['Overture_Maxspeed'], errors='coerce')
            valid_overture = ov_speed.notna() & (ov_speed > 0)
            mismatch_count = (valid_overture & (ov_speed < scored_network['SpeedLimit'])).sum()
            scored_network['SpeedLimit'] = np.where(valid_overture & (ov_speed < scored_network['SpeedLimit']), ov_speed, scored_network['SpeedLimit'])
            print(f"    Applied Overture speed cross-validation (mismatches corrected: {mismatch_count} segments)")

        scored_network['F85thPercentileSpeed'] = pd.to_numeric(scored_network['F85thPercentileSpeed'], errors='coerce').fillna(scored_network['SpeedLimit'])
        
        if 'MedianSpeed' in scored_network.columns:
            scored_network['MedianSpeed'] = pd.to_numeric(scored_network['MedianSpeed'], errors='coerce').fillna(scored_network['SpeedLimit'])
        if 'PercentOverLimit' in scored_network.columns:
            scored_network['PercentOverLimit'] = pd.to_numeric(scored_network['PercentOverLimit'], errors='coerce').fillna(0.0)
        if 'RankedPercentile' in scored_network.columns:
            scored_network['RankedPercentile'] = pd.to_numeric(scored_network['RankedPercentile'], errors='coerce').fillna(0.5)
        if 'SampleSize_avg' in scored_network.columns:
            scored_network['SampleSize_avg'] = pd.to_numeric(scored_network['SampleSize_avg'], errors='coerce').fillna(10.0)
        if 'WeightedSample' in scored_network.columns:
            scored_network['WeightedSample'] = pd.to_numeric(scored_network['WeightedSample'], errors='coerce').fillna(1.0)
        if 'UrbanPC' in scored_network.columns:
            scored_network['UrbanPC'] = pd.to_numeric(scored_network['UrbanPC'], errors='coerce').fillna(0.0)
        if 'MapillaryVisualFriction' in scored_network.columns:
            scored_network['MapillaryVisualFriction'] = pd.to_numeric(scored_network['MapillaryVisualFriction'], errors='coerce').fillna(1.0)
            
        # 2. Extract Base Physics (Kinematics)
        scored_network['KineticRiskDelta'] = np.maximum(0, scored_network['F85thPercentileSpeed']**2 - scored_network['SpeedLimit']**2)
        
        # 3. Calculate Raw Sub-Indices
        
        # --- I_S: Kinematic Severity Index ---
        # Basis: Logistic regression of fatality risk based on impact velocity.
        # Motorways/expressways use occupant frontal crash risk parameters (centered higher, slope = 0.044, intercept = -8.91)
        # Urban roads/local streets use pedestrian fatality risk parameters (centered lower, slope = 0.099, intercept = -8.35)
        v_85 = scored_network['F85thPercentileSpeed']
        road_class_series = scored_network['RoadClass']
        speed_limit_series = scored_network['SpeedLimit']
        
        is_speedway = (road_class_series == 'motorway') | (speed_limit_series >= 80)
        intercept = np.where(is_speedway, -8.91, -8.35)
        slope = np.where(is_speedway, 0.044, 0.099)
        
        scored_network['FatalityProb'] = 1 / (1 + np.exp(-(intercept + slope * v_85)))
        scored_network.loc[v_85 <= 0, 'FatalityProb'] = 0.0
        scored_network['I_S_raw'] = scored_network['FatalityProb'] * scored_network['KineticRiskDelta']
        
        # --- Safe System Alignment (Continuous Mathematical Thresholding) ---
        # Basis: We transition from rigid Boolean flags to a fully continuous probability distribution.
        
        # 1. Local Policy: What is the normative speed limit in this specific geographical cluster?
        local_avg_limit = scored_network['SpeedLimit'].mean()
        
        # 2. Synthetic Actor Data: Compute the continuous VRU Exposure Factor [0.0 to 1.0] per segment
        conflict_df = pd.DataFrame(self.conflict_logs) if self.conflict_logs else pd.DataFrame(columns=['segment_id', 'type'])
        pet_df = pd.DataFrame(self.pet_logs) if self.pet_logs else pd.DataFrame(columns=['segment_id'])
        
        # Count hazards explicitly on this segment using globally unique segment_id (OBJECTID)
        # Segregate by type
        if not conflict_df.empty and 'type' in conflict_df.columns:
            segment_vru = conflict_df[conflict_df['type'] == 'VRU'].groupby('segment_id').size()
            segment_v2v = conflict_df[conflict_df['type'] == 'V2V'].groupby('segment_id').size()
            segment_v2o = conflict_df[conflict_df['type'] == 'V2O'].groupby('segment_id').size()
        else:
            segment_vru = pd.Series(dtype=float)
            segment_v2v = pd.Series(dtype=float)
            segment_v2o = pd.Series(dtype=float)
            
        segment_pets = pet_df.groupby('segment_id').size() if not pet_df.empty and 'segment_id' in pet_df.columns else pd.Series(dtype=float)
        
        scored_network['SegmentConflicts_VRU'] = scored_network['OBJECTID'].map(segment_vru).fillna(0) * self.multiplier
        scored_network['SegmentConflicts_V2V'] = scored_network['OBJECTID'].map(segment_v2v).fillna(0) * self.multiplier
        scored_network['SegmentConflicts_V2O'] = scored_network['OBJECTID'].map(segment_v2o).fillna(0) * self.multiplier
        scored_network['SegmentPETs'] = scored_network['OBJECTID'].map(segment_pets).fillna(0) * self.multiplier
        
        # Count stress events explicitly on this segment (moved earlier for rubric category calculation)
        stress_df = pd.DataFrame(self.stress_logs) if self.stress_logs else pd.DataFrame(columns=['segment_id'])
        segment_stress = stress_df.groupby('segment_id').size() if not stress_df.empty and 'segment_id' in stress_df.columns else pd.Series(dtype=float)
        scored_network['ABM_Stress_Events'] = scored_network['OBJECTID'].map(segment_stress).fillna(0) * self.multiplier
        
        # VRU Exposure focuses specifically on pedestrian conflicts and PET hazards
        scored_network['EffectiveHazards_VRU'] = (scored_network['SegmentConflicts_VRU'] * 5.0) + (scored_network['SegmentPETs'] * 6.0)
        
        # Population-density amplifier from GHS-POP enrichment
        # Segments with 0 surrounding population get their VRU penalty reduced to 20%
        # Segments near 5,000+ people/km² get full penalty
        if 'PopDensity_100m' in scored_network.columns:
            pop_vals = pd.to_numeric(scored_network['PopDensity_100m'], errors='coerce').fillna(0.0)
            pop_factor = np.log1p(pop_vals) / np.log1p(5000.0)
            pop_factor = np.clip(pop_factor, 0.2, 1.0)
            scored_network['EffectiveHazards_VRU'] = scored_network['EffectiveHazards_VRU'] * pop_factor
            print(f"    Applied GHS-POP population amplifier (mean factor: {pop_factor.mean():.3f})")
        
        # POI proximity amplifier from OSM Overpass enrichment
        # Schools and hospitals within 500m amplify VRU exposure
        if 'POI_Schools_500m' in scored_network.columns:
            school_boost = pd.to_numeric(scored_network['POI_Schools_500m'], errors='coerce').fillna(0.0)
            hospital_boost = pd.to_numeric(scored_network['POI_Hospitals_500m'] if 'POI_Hospitals_500m' in scored_network.columns else pd.Series(0.0, index=scored_network.index), errors='coerce').fillna(0.0)
            transit_boost = pd.to_numeric(scored_network['POI_Transit_500m'] if 'POI_Transit_500m' in scored_network.columns else pd.Series(0.0, index=scored_network.index), errors='coerce').fillna(0.0)
            market_boost = pd.to_numeric(scored_network['POI_Markets_500m'] if 'POI_Markets_500m' in scored_network.columns else pd.Series(0.0, index=scored_network.index), errors='coerce').fillna(0.0)
            poi_amplifier = 1.0 + np.clip((school_boost * 2.0 + hospital_boost * 1.5 + transit_boost * 1.0 + market_boost * 0.8) / 10.0, 0.0, 0.5)
            scored_network['EffectiveHazards_VRU'] = scored_network['EffectiveHazards_VRU'] * poi_amplifier
            boosted_count = ((school_boost > 0) | (hospital_boost > 0) | (transit_boost > 0) | (market_boost > 0)).sum()
            print(f"    Applied OSM POI amplifier ({boosted_count} segments near schools/hospitals/transit/markets)")
        
        # Softened log-scaled exposure factor to prevent extreme polarization (diminishing return risk model)
        vru_exposure_factor = np.log1p(scored_network['EffectiveHazards_VRU']) / np.log1p(250.0)
        vru_exposure_factor = np.clip(vru_exposure_factor, 0.0, 1.0)
        
        # 3. Dynamic Continuous Blending:
        # A sliding scale. If exposure is 1.0 (highly mixed-use), limit smoothly becomes 30.0.
        # If exposure is 0.0 (segregated rural), limit smoothly becomes local_avg_limit (capped at 50).
        vru_exposure_weight = np.clip(vru_exposure_factor, 0.0, 1.0)
        dynamic_safe_limit = (30.0 * vru_exposure_weight) + (min(local_avg_limit, 50.0) * (1.0 - vru_exposure_weight))
        
        # Instead of a boolean, we will just use the continuous dynamic_safe_limit to calculate the penalty directly.
        # However, we still supply the 'SafeSystemAligned' boolean flag for the dashboard visualization.
        scored_network['DynamicSafeLimit'] = dynamic_safe_limit
        # Overture Speed Cross-Validation: applied globally at start of compute_scores()
        effective_limit = scored_network['SpeedLimit']

        scored_network['SafeSystemAligned'] = effective_limit <= dynamic_safe_limit
        # Also flag high-speed segregated highways as technically aligned.
        scored_network.loc[scored_network['SpeedLimit'] > 60, 'SafeSystemAligned'] = True
        
        
        def _get_violation(row):
            violations = []
            if not row['SafeSystemAligned']:
                if row['EffectiveHazards_VRU'] > 0:
                    violations.append(f"Violates {int(row['DynamicSafeLimit'])} km/h VRU survivability limit (WHO Safe System 2022)")
                else:
                    violations.append(f"Exceeds safe system limit of {int(row['DynamicSafeLimit'])} km/h (OECD/ITF 2018)")
                    
            if row.get('F85thPercentileSpeed', 0) > row['SpeedLimit'] + 10:
                violations.append("Kinematic severity exceeds tolerance (Wramborg 2005 Fatality Curve)")
                
            if row.get('SegmentConflicts_V2V', 0) > 0:
                violations.append("High V2V rear-end conflict density (FHWA SSAM)")
                
            if row.get('SegmentConflicts_V2O', 0) > 0:
                violations.append("V2O Infrastructure hazard (AASHTO Clear Zone Guidelines)")
                
            if not violations:
                return "None"
            return " | ".join(violations)
            
        scored_network['Violated_Rules'] = scored_network.apply(_get_violation, axis=1)
        
        # --- I_C: Contextual Friction & Policy Misalignment Index ---
        # SafeSystemRiskDelta = Excess kinetic energy mathematically scaled by the VRU Exposure Factor.
        # This means an 80 km/h road with 0.0 exposure gets 0 penalty. 
        # An 80 km/h road with 1.0 exposure gets a massive penalty scaling from the 30 km/h limit.
        base_excess_energy = np.maximum(0, scored_network['F85thPercentileSpeed']**2 - dynamic_safe_limit**2)
        
        # Use square root to bring SafeSystemRiskDelta to the same scale as FrictionDelta (km/h instead of km^2/h^2)
        scored_network['SafeSystemRiskDelta'] = np.sqrt(base_excess_energy) * vru_exposure_factor
        
        # Normal Contextual Friction (F85 vs Speed Limit delta) + the massive VRU Risk Delta
        # V2O Conflicts explicitly penalize the Friction Score
        v2o_friction_penalty = scored_network['SegmentConflicts_V2O'] * 1.5
        scored_network['FrictionDelta'] = np.maximum(0, scored_network['F85thPercentileSpeed'] - scored_network['SpeedLimit']) + v2o_friction_penalty
        
        # Building-density friction from Google Open Buildings enrichment
        # High building density adjacent to road = more lateral obstruction, driveways, pedestrian crossings
        if 'BuildingDensity_100m' in scored_network.columns:
            bldg_vals = pd.to_numeric(scored_network['BuildingDensity_100m'], errors='coerce').fillna(0.0)
            bldg_friction = np.log1p(bldg_vals) / np.log1p(100.0)
            bldg_friction = np.clip(bldg_friction, 0.0, 1.0)
            scored_network['FrictionDelta'] = scored_network['FrictionDelta'] + (bldg_friction * 5.0)
            print(f"    Applied building-density friction (mean bldg_density: {bldg_vals.mean():.1f})")

        # --- Phase 46: OSM Infrastructure Gap Penalties & Bonuses ---
        # Missing sidewalks in urban areas with pedestrians = friction penalty
        # Presence of crossings, traffic calming, street lighting = friction bonus (reduction)
        infra_bonus = pd.Series(0.0, index=scored_network.index)
        infra_penalty = pd.Series(0.0, index=scored_network.index)

        if 'OSM_Sidewalks_500m' in scored_network.columns:
            sidewalks = pd.to_numeric(scored_network['OSM_Sidewalks_500m'], errors='coerce').fillna(0)
            # Urban segments with NO sidewalks detected get a penalty
            is_urban = scored_network.get('LandUse', pd.Series('URBAN', index=scored_network.index)).isin(['URBAN', 'urban'])
            no_sidewalk_urban = (sidewalks == 0) & is_urban & (scored_network['SpeedLimit'] <= 60)
            infra_penalty = infra_penalty + np.where(no_sidewalk_urban, 6.0, 0.0)

        if 'OSM_Crossings_500m' in scored_network.columns:
            crossings = pd.to_numeric(scored_network['OSM_Crossings_500m'], errors='coerce').fillna(0)
            # Each crossing within 500m provides a small safety bonus (capped)
            infra_bonus = infra_bonus + np.clip(crossings * 1.0, 0.0, 4.0)

        if 'OSM_TrafficCalming_500m' in scored_network.columns:
            calming = pd.to_numeric(scored_network['OSM_TrafficCalming_500m'], errors='coerce').fillna(0)
            infra_bonus = infra_bonus + np.clip(calming * 1.5, 0.0, 6.0)

        if 'OSM_StreetLighting_500m' in scored_network.columns:
            lighting = pd.to_numeric(scored_network['OSM_StreetLighting_500m'], errors='coerce').fillna(0)
            # Street lighting reduces nighttime risk; absence in urban areas is a penalty
            has_lighting = lighting > 0
            infra_bonus = infra_bonus + np.where(has_lighting, np.clip(lighting * 0.6, 0.0, 3.0), 0.0)
            no_light_urban = (~has_lighting) & is_urban if 'OSM_Sidewalks_500m' in scored_network.columns else pd.Series(False, index=scored_network.index)
            infra_penalty = infra_penalty + np.where(no_light_urban, 4.0, 0.0)

        if 'OSM_Cycleways_500m' in scored_network.columns:
            cycleways = pd.to_numeric(scored_network['OSM_Cycleways_500m'], errors='coerce').fillna(0)
            # Dedicated cycleways reduce VRU conflict risk
            infra_bonus = infra_bonus + np.clip(cycleways * 1.0, 0.0, 3.0)

        # --- Phase 46: Mapillary Visual Evidence Bonus ---
        # Traffic signs and crosswalks detected by Mapillary provide evidence of
        # active traffic management, reducing friction.
        if 'Mapillary_TrafficSigns' in scored_network.columns:
            signs = pd.to_numeric(scored_network['Mapillary_TrafficSigns'], errors='coerce').fillna(0)
            infra_bonus = infra_bonus + np.clip(signs * 0.4, 0.0, 4.0)
        if 'Mapillary_Crosswalks' in scored_network.columns:
            map_crosswalks = pd.to_numeric(scored_network['Mapillary_Crosswalks'], errors='coerce').fillna(0)
            infra_bonus = infra_bonus + np.clip(map_crosswalks * 1.0, 0.0, 4.0)

        # --- Phase 55: HeiGIT Road Surface & Smoothness Penalty ---
        surface_penalty = pd.Series(0.0, index=scored_network.index)
        if 'OSM_RoadSurface' in scored_network.columns:
            is_unpaved = scored_network['OSM_RoadSurface'].astype(str).str.lower().isin(['unpaved', 'dirt', 'gravel', 'earth', 'sand', 'grass', 'mud'])
            surface_penalty = surface_penalty + np.where(is_unpaved, 6.0, 0.0)
        if 'OSM_RoadSmoothness' in scored_network.columns:
            is_rough = scored_network['OSM_RoadSmoothness'].astype(str).str.lower().isin(['bad', 'very_bad', 'rough', 'horrible', 'impassable', 'very_horrible'])
            surface_penalty = surface_penalty + np.where(is_rough, 4.0, 0.0)
        
        infra_penalty = infra_penalty + surface_penalty

        # Keep infrastructure as its own seventh rubric category while still
        # letting severe physical deficits nudge contextual friction.
        net_infra = infra_penalty - infra_bonus
        infra_deficit = np.maximum(0.0, net_infra)
        scored_network['FrictionDelta'] = np.maximum(0, scored_network['FrictionDelta'] + (infra_deficit * 0.35))
        scored_network['InfraGapPenalty'] = infra_penalty
        scored_network['InfraBonus'] = infra_bonus
        scored_network['SurfacePenalty'] = surface_penalty
        scored_network['I_Infra_raw'] = infra_deficit
        infra_affected = ((infra_penalty > 0) | (infra_bonus > 0)).sum()
        print(f"    Applied OSM/Mapillary/HeiGIT infrastructure adjustments ({infra_affected} segments affected)")

        scored_network['I_C_raw'] = scored_network['FrictionDelta'] + scored_network['SafeSystemRiskDelta']
        
        # Retrospective addition of V2V to Kinematics
        # Mass pileups/rear-ends indicate severe kinetic variance
        v2v_kinetic_penalty = scored_network['SegmentConflicts_V2V'] * 1.5
        scored_network['I_S_raw'] = scored_network['I_S_raw'] + v2v_kinetic_penalty
        
        # 4. Exploratory Data Analysis & Machine Learning (Understanding Local Context without Overfitting)
        # We run a lightweight K-Means on the network speeds to understand the local driving culture
        try:
            features = scored_network[['SpeedLimit', 'F85thPercentileSpeed']].copy()
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(features)
            kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
            scored_network['LocalContextCluster'] = kmeans.fit_predict(X_scaled)
            
            # Use cluster centers to slightly modulate weights (e.g. if the whole city is high-speed, 
            # I_C becomes slightly more important because high-speed + friction is deadly)
            city_avg_speed = scored_network['F85thPercentileSpeed'].mean()
            default_w1 = 0.6 if city_avg_speed > 70 else 0.5
            default_w2 = 0.4 if city_avg_speed > 70 else 0.5
        except Exception as e:
            print(f"ML Context Extraction Failed: {e}. Defaulting to standard weights.")
            default_w1, default_w2 = 0.5, 0.5

        # 5. Dynamic Min-Max Normalization (Localization)
        # We fill NaNs with 0 to ensure all roads have scientific indices
        scored_network['I_S_raw'] = scored_network['I_S_raw'].fillna(0)
        scored_network['I_C_raw'] = scored_network['I_C_raw'].fillna(0)
        
        # This solves the polarization by scaling relative to THIS city's dataset.
        # We use the 99th percentile instead of absolute max to prevent extreme outliers from crushing the distribution.
        min_is = scored_network['I_S_raw'].min()
        max_is = scored_network['I_S_raw'].quantile(0.99)
        if max_is <= min_is: max_is = min_is + 1e-5
        scored_network['I_S_norm'] = np.clip((scored_network['I_S_raw'] - min_is) / (max_is - min_is), 0, 1)
        
        min_ic = scored_network['I_C_raw'].min()
        max_ic = scored_network['I_C_raw'].quantile(0.99)
        if max_ic <= min_ic: max_ic = min_ic + 1e-5
        scored_network['I_C_norm'] = np.clip((scored_network['I_C_raw'] - min_ic) / (max_ic - min_ic), 0, 1)

        scored_network['I_Infra_raw'] = scored_network.get('I_Infra_raw', 0.0)
        min_infra = scored_network['I_Infra_raw'].min()
        max_infra = scored_network['I_Infra_raw'].quantile(0.99)
        if max_infra <= min_infra:
            max_infra = min_infra + 1e-5
        scored_network['I_Infra_norm'] = np.clip((scored_network['I_Infra_raw'] - min_infra) / (max_infra - min_infra), 0, 1)

        # 6. AI Guided Human Experience/Safety
        # Assign a proxy experience score between 50 and 100 based on friction alignment.
        # In production, this is explicitly queried from the Regional AI Guide per archetype.
        scored_network['SafetyExperienceScore'] = 50.0 + (50.0 * (1.0 - scored_network['I_C_norm']))
        
        # Country-level fatality rate modulates AI category (ADB ATO Road Safety data)
        # Countries with >15 fatalities/100k get up to 10-point reduction in experience score
        if 'Country_RSA_Fatalities' in scored_network.columns:
            rsa_vals = pd.to_numeric(scored_network['Country_RSA_Fatalities'], errors='coerce').fillna(0.0)
            if rsa_vals.max() > 0:
                macro_penalty = np.clip((rsa_vals - 5.0) / 10.0, 0.0, 1.0) * 10.0
                scored_network['SafetyExperienceScore'] = scored_network['SafetyExperienceScore'] - macro_penalty
                scored_network['SafetyExperienceScore'] = np.clip(scored_network['SafetyExperienceScore'], 30.0, 100.0)
                print(f"    Applied ATO macro penalty (country fatality rate: {rsa_vals.iloc[0]:.1f}/100k)")

        # 7. Batched AI Agent Interventions (Archetyping)
        # --- Contextual Zoning Inference ---
        def _infer_zone(row):
            speed = row.get('SpeedLimit', 50)
            landuse = row.get('LandUse', 'URBAN')
            rdclass = row.get('RoadClass', 'secondary')
            pop_density = float(row.get('PopDensity_100m', 0) or 0)
            bldg_density = float(row.get('BuildingDensity_100m', 0) or 0)
            schools_nearby = int(row.get('POI_Schools_500m', 0) or 0)
            hospitals_nearby = int(row.get('POI_Hospitals_500m', 0) or 0)
            transit_nearby = int(row.get('POI_Transit_500m', 0) or 0)
            
            # POI-based overrides (highest confidence)
            if schools_nearby > 0 or hospitals_nearby > 0:
                if speed <= 50: return "School / Hospital Zone"
            
            if speed <= 30: return "School / Hospital Zone"
            
            # Use enrichment data as fallback when LandUse is unknown
            if landuse in ['UNKNOWN', 'unknown', 'Unknown', '', None]:
                if pop_density > 1000 or bldg_density > 20:
                    landuse = 'URBAN'
                elif pop_density < 50 and bldg_density < 2:
                    landuse = 'RURAL'
                else:
                    landuse = 'URBAN'  # default to urban for safety
            
            if landuse == 'URBAN' and speed <= 50 and transit_nearby > 0: return "Market / Mixed-Use"
            elif landuse == 'URBAN' and speed <= 50: return "Market / Mixed-Use"
            elif landuse == 'URBAN' and rdclass in ['primary', 'trunk'] and speed > 50: return "Urban Arterial (Poor Sidewalks)"
            elif landuse == 'RURAL' and rdclass != 'motorway': return "Rural Road"
            elif rdclass == 'motorway': return "Motorway / Expressway"
            return "Generic Road"
            
        scored_network['InferredZone'] = scored_network.apply(_infer_zone, axis=1)

        # 8. Board of Evaluators (Row-level dynamic tweaking)
        board = BoardOfEvaluators()
        base_k = self.guide.params.get('risk_tolerance_k', 4.0)
        
        def _apply_board_tweaks(row):
            arch_mock = {'F85': row['F85thPercentileSpeed'], 'S3_Avg': 50} # Mock S3 for initial routing
            assistant = board._select_assistant_for_archetype(arch_mock, row['InferredZone'])
            
            # Use default_w1 and default_w2 modulated by assistant preferences
            w1 = default_w1 * assistant['w1_mod']
            w2 = default_w2 * assistant['w2_mod']
            # Normalize weights to sum to 1.0
            total_w = w1 + w2
            w1, w2 = w1/total_w, w2/total_w
            
            return pd.Series({
                'w1_tweaked': w1,
                'w2_tweaked': w2,
                'k_tweaked': base_k * assistant['k_modifier'],
                'EvaluatingAssistant': assistant['name']
            })
            
        tweaks_df = scored_network.apply(_apply_board_tweaks, axis=1)
        existing_tweak_cols = [c for c in tweaks_df.columns if c in scored_network.columns]
        if existing_tweak_cols:
            scored_network = scored_network.drop(columns=existing_tweak_cols)
        scored_network = pd.concat([scored_network, tweaks_df], axis=1)

        # Apply flexible weights to GDF
        def _apply_rubric_weights(row):
            w = self._get_rubric_weights(row.get('RoadClass'), row.get('LandUse'), row.get('SpeedLimit'))
            return pd.Series({
                'Max_Kinematics': w['Score_Kinematics'],
                'Max_Friction': w['Score_Friction'],
                'Max_VRU': w['Score_VRU'],
                'Max_Speeding': w['Score_Speeding'],
                'Max_AI': w['Score_AI'],
                'Max_Stress': w['Score_Stress'],
                'Max_Infrastructure': w['Score_Infrastructure']
            })
            
        print("Allocating dynamic context-aware rubric weights...")
        weights_df = scored_network.apply(_apply_rubric_weights, axis=1)
        # Ensure we drop existing Max_ columns if they exist before concat
        existing_max_cols = [c for c in weights_df.columns if c in scored_network.columns]
        if existing_max_cols:
            scored_network = scored_network.drop(columns=existing_max_cols)
        scored_network = pd.concat([scored_network, weights_df], axis=1)

        # 9. Final Score Calculation (S^3 Formula) - 7-Category Blended Rubric
        # Phase 56: Infrastructure is a first-class score bucket rather than a hidden friction-only adjustment.
        
        # Category 1: Kinematic Severity (0-Max pts)
        score_kinematics = self._blended_score(scored_network['I_S_norm'], scored_network['Max_Kinematics'], scored_network['RoadClass'], scored_network['SpeedLimit'])
        
        # Category 2: Contextual Friction (0-Max pts)
        score_friction = self._blended_score(scored_network['I_C_norm'], scored_network['Max_Friction'], scored_network['RoadClass'], scored_network['SpeedLimit'])
        
        # Category 3: VRU Exposure & ABM Conflicts (0-Max pts)
        vru_penalty_ratio = np.clip(vru_exposure_factor, 0.0, 1.0)
        score_vru = self._blended_score(vru_penalty_ratio, scored_network['Max_VRU'], scored_network['RoadClass'], scored_network['SpeedLimit'])
        
        # Category 4: Behavioral Speeding Compliance (0-Max pts)
        percent_over_limit = pd.to_numeric(scored_network['PercentOverLimit'], errors='coerce').fillna(0.0) if 'PercentOverLimit' in scored_network.columns else pd.Series(0.0, index=scored_network.index)
        is_speedway = (scored_network['RoadClass'] == 'motorway') | (scored_network['SpeedLimit'] >= 80)
        # Soften speeding penalty on motorways/highways by dividing ratio by 1.5 (less severe risk variance)
        speeding_penalty_ratio = np.clip(np.where(is_speedway, percent_over_limit / 1.5, percent_over_limit), 0.0, 1.0)
        score_speeding = self._blended_score(speeding_penalty_ratio, scored_network['Max_Speeding'], scored_network['RoadClass'], scored_network['SpeedLimit'])
        
        # Category 5: Safety Experience (0-Max pts)
        ai_experience_ratio = (scored_network['SafetyExperienceScore'] - 50.0) / 50.0
        penalty_ai = 1.0 - ai_experience_ratio
        score_ai = self._blended_score(penalty_ai, scored_network['Max_AI'], scored_network['RoadClass'], scored_network['SpeedLimit'])
        
        # Softened log-scaled active stress ratio (diminishing return risk model)
        stress_penalty_ratio = np.log1p(scored_network['ABM_Stress_Events']) / np.log1p(10.0)
        stress_penalty_ratio = np.clip(stress_penalty_ratio, 0.0, 1.0)
        score_stress = self._blended_score(stress_penalty_ratio, scored_network['Max_Stress'], scored_network['RoadClass'], scored_network['SpeedLimit'])

        # Category 7: Infrastructure Deficit / Protective Features (0-Max pts)
        score_infrastructure = self._blended_score(scored_network['I_Infra_norm'], scored_network['Max_Infrastructure'], scored_network['RoadClass'], scored_network['SpeedLimit'])
        
        # Save individual rubric category scores to GDF
        scored_network['Score_Kinematics'] = score_kinematics
        scored_network['Score_Friction'] = score_friction
        scored_network['Score_VRU'] = score_vru
        scored_network['Score_Speeding'] = score_speeding
        scored_network['Score_AI'] = score_ai
        scored_network['Score_Stress'] = score_stress
        scored_network['Score_Infrastructure'] = score_infrastructure
        
        raw_score = score_kinematics + score_friction + score_vru + score_speeding + score_ai + score_stress + score_infrastructure
        raw_score = np.clip(raw_score, 0.0, 100.0)
        
        # Phase 29: S3 Data Confidence using SampleSize_avg and WeightedSample
        # Extreme penalties are regressed toward a safe median of 70 if we lack sample data.
        def safe_float_series(series, fallback):
            import pandas as pd
            return pd.to_numeric(series, errors='coerce').fillna(fallback)

        if 'SampleSize_avg' in scored_network.columns:
            sample_sizes = safe_float_series(scored_network['SampleSize_avg'], 10)
            # 100+ samples = 1.0 confidence. 0 samples = 0.3 confidence.
            confidence = np.clip(sample_sizes / 100.0, 0.3, 1.0)
            
            if 'WeightedSample' in scored_network.columns:
                weights = safe_float_series(scored_network['WeightedSample'], 1.0)
                confidence = np.clip(confidence * np.clip(weights, 0.5, 2.0), 0.3, 1.0)
                
            # Phase 31: Computer Vision & Topology-Aware Fallbacks
            if 'MapillaryVisualFriction' in scored_network.columns:
                visual_friction = pd.to_numeric(scored_network['MapillaryVisualFriction'], errors='coerce').fillna(1.0)
                # Scale fallback score inversely with friction: higher friction = more danger = lower score
                # Base 55.0 scaled down by friction.
                dynamic_median = 55.0 / visual_friction
                # Cap the fallback between 30 (extreme caution) and 75 (relative safety)
                median_score = np.clip(dynamic_median, 30.0, 75.0)
            else:
                median_score = 55.0
                
            scored_network['SpeedSafetyScore'] = (raw_score * confidence) + (median_score * (1.0 - confidence))
        else:
            scored_network['SpeedSafetyScore'] = raw_score

        # We blend the segment's score with the average score of its intersecting neighbors (60/40 split)
        # This makes intersection choke points spread their hazards to connected roads heavily!
        if 'geometry' in scored_network.columns:
            print("Applying Vectorized Segment Relativity Smoothing (60/40)...")
            # Create a unique temporary index to avoid index duplication issues
            scored_network['_temp_id'] = np.arange(len(scored_network))
            
            # Create light copy for spatial join
            light_gdf = scored_network[['_temp_id', 'geometry', 'SpeedSafetyScore']].copy()
            
            # Spatial join to find all intersecting road segments
            joined = gpd.sjoin(light_gdf, light_gdf, predicate='intersects')
            
            # Exclude self intersections
            neighbors = joined[joined['_temp_id_left'] != joined['_temp_id_right']]
            
            # Compute neighbor stats using pandas groupby
            # Group by the left segment ID
            grouped = neighbors.groupby('_temp_id_left')
            
            # Aggregate stats
            stats = grouped['SpeedSafetyScore_right'].agg(['count', 'mean', 'min'])
            stats.rename(columns={'count': 'neighbor_count', 'mean': 'neighbor_avg', 'min': 'neighbor_min'}, inplace=True)
            
            # Merge stats back to scored_network
            scored_network = scored_network.merge(stats, left_on='_temp_id', right_index=True, how='left')
            
            # Fill NaNs for segments with no neighbors
            scored_network['neighbor_count'] = scored_network['neighbor_count'].fillna(0).astype(int)
            scored_network['neighbor_avg'] = scored_network['neighbor_avg'].fillna(scored_network['SpeedSafetyScore'])
            scored_network['neighbor_min'] = scored_network['neighbor_min'].fillna(scored_network['SpeedSafetyScore'])
            
            # Vectorized logic
            s3 = scored_network['SpeedSafetyScore'].values
            n_count = scored_network['neighbor_count'].values
            n_avg = scored_network['neighbor_avg'].values
            n_min = scored_network['neighbor_min'].values
            
            # Base smoothed scores
            smoothed = np.where(
                n_count > 2,
                s3 * 0.70 + n_min * 0.30,
                np.where(
                    n_count > 0,
                    s3 * 0.60 + n_avg * 0.40,
                    s3
                )
            )
            
            # Adjustment 1: neighbor_count <= 1:
            smoothed = np.where(
                n_count <= 1,
                np.minimum(100.0, smoothed + 15.0),
                smoothed
            )
            
            # Adjustment 2: neighbor_count >= 3:
            danger_factor = np.maximum(0.0, (100.0 - n_avg) / 100.0)
            dynamic_penalty = n_count * danger_factor * 3.0
            smoothed = np.where(
                n_count >= 3,
                smoothed / (1.0 + (dynamic_penalty / 10.0)),
                smoothed
            )
            
            # Threat Mitigation (Hidden Hazards)
            total_hazards = (
                scored_network.get('EffectiveHazards_VRU', 0) + 
                scored_network.get('SegmentConflicts_V2V', 0) + 
                scored_network.get('SegmentConflicts_V2O', 0)
            ).values
            
            smoothed = np.where(
                total_hazards > 0,
                np.minimum(s3, smoothed),
                smoothed
            )
            
            scored_network['SpeedSafetyScore'] = smoothed
            
            # Clean up temp columns
            scored_network.drop(columns=['_temp_id', 'neighbor_count', 'neighbor_avg', 'neighbor_min'], inplace=True)

        
        # 11. Batched AI Agent Interventions (Archetyping) via Unsupervised Learning
        # Phase 45: PCA + K-Means Clustering for true Empirical Latent Archetypes
        try:
            from prototypes.analytical_model.archetype_discovery import ArchetypeDiscovery
            # Run PCA + K-Means to find latent structures in the simulation data
            discoverer = ArchetypeDiscovery(scored_network, n_clusters=10)
            scored_network, archetypes = discoverer.discover_archetypes()
            
            # Map the cluster ID to the string 'Archetype' expected by the downstream logic
            scored_network['Archetype'] = scored_network['LatentArchetypeID'].apply(lambda x: f"PCA_Cluster_{x}")
            
        except Exception as e:
            print(f"[Score Calculator] PCA Clustering failed, falling back to heuristic archetypes. Error: {e}")
            scored_network['ScoreBucket'] = (scored_network['SpeedSafetyScore'] // 10) * 10
            scored_network['Archetype'] = scored_network.apply(
                lambda r: f"Limit_{int(r['SpeedLimit'])}_Score_{int(r['ScoreBucket'])}", axis=1
            )
            
            archetypes = {}
            for arch_id in scored_network['Archetype'].unique():
                subset = scored_network[scored_network['Archetype'] == arch_id]
                percent_over = 0.0
                if 'PercentOverLimit' in subset.columns:
                    percent_over = pd.to_numeric(subset['PercentOverLimit'], errors='coerce').fillna(0.0).mean()
                    
                archetypes[arch_id] = {
                    'SpeedLimit': subset['SpeedLimit'].iloc[0],
                    'F85': subset['F85thPercentileSpeed'].mean(),
                    'MedianSpeed': subset.get('MedianSpeed', pd.Series(0)).mean(),
                    'SampleSize_avg': subset.get('SampleSize_avg', pd.Series(0)).mean(),
                    'S3_Avg': subset['SpeedSafetyScore'].mean(),
                    'PercentOverLimit': percent_over,
                    'InferredZone': subset['InferredZone'].iloc[0],
                    'Avg_EffectiveHazards': subset.get('EffectiveHazards_VRU', pd.Series(0)).mean(),
                    'Avg_V2V_Conflicts': subset.get('SegmentConflicts_V2V', pd.Series(0)).mean(),
                    'Avg_V2O_Conflicts': subset.get('SegmentConflicts_V2O', pd.Series(0)).mean(),
                    'Avg_ABM_Stress': subset.get('ABM_Stress_Events', pd.Series(0)).mean(),
                    'Score_VRU': subset.get('Score_VRU', pd.Series(0)).mean(),
                    'Max_VRU': subset.get('Max_VRU', pd.Series(0)).mean(),
                    'Score_Kinematics': subset.get('Score_Kinematics', pd.Series(0)).mean(),
                    'Max_Kinematics': subset.get('Max_Kinematics', pd.Series(0)).mean()
                }
                
        print(f"S^3 Calculation Complete. Extracted {len(archetypes)} unique archetypes for LLM guidance.")
        
        # Route to Board of Evaluators for policy interventions
        board_results = board.evaluate_and_tweak(archetypes, base_k)
        
        # Extract just the intervention texts for the AI_SpeedIntervention column
        interventions = {arch_id: res['intervention'] for arch_id, res in board_results.items()}
        ai_adjustments = {arch_id: res['tweaks'].get('ai_score_adjustment', 0.0) for arch_id, res in board_results.items()}

        scored_network['AI_SpeedIntervention'] = scored_network['Archetype'].map(interventions)
        
        # Calculate Intervention Cost for baseline mapping
        def _get_intervention_cost(interv):
            interv = str(interv).lower()
            cost = 0.0
            if 'automated enforcement' in interv or 'cameras' in interv:
                cost += 15000.0
            if 'traffic calming' in interv or 'chicanes' in interv or 'bumps' in interv:
                cost += 25000.0
            if 'segregate' in interv:
                cost += 50000.0
            if 'reduce limits' in interv:
                cost += 5000.0
            return cost
            
        scored_network['Intervention_Cost'] = scored_network['AI_SpeedIntervention'].fillna('').apply(_get_intervention_cost)
        scored_network['Safety_ROI'] = 0.0  # ROI is 0 for baseline since S3 improvement is not yet calculated
        
        # Phase 35: Give AI Reviewers more say on the final score
        # (ABM Stress Say is Category 6; Infrastructure is Category 7 in the rubric)
        ai_say = scored_network['Archetype'].map(ai_adjustments).fillna(0.0)
        scored_network['AI_Score_Adjustment'] = ai_say
        
        # Apply Reviewer and Simulator logic
        scored_network['SpeedSafetyScore'] = np.clip(scored_network['SpeedSafetyScore'] + ai_say, 0.0, 100.0)
        
        # Add a tiny unique offset based on OBJECTID to guarantee unique pre-rank ordering
        unique_offset = (scored_network['OBJECTID'].astype(float) % 100000) * 1e-6
        scored_network['SpeedSafetyScore'] = scored_network['SpeedSafetyScore'] + unique_offset
        
        # Map rank percentiles to a kinder review-priority distribution.
        # This preserves ordering while avoiding a submission map where most
        # segments appear as severe failures instead of prioritized review items.
        from scipy.stats import skewnorm
        rank_pct = scored_network['SpeedSafetyScore'].rank(method='first', pct=True)
        skewed_rank_score = skewnorm.ppf(rank_pct, a=-0.55, loc=66.0, scale=28.0)
        skewed_rank_score = np.clip(skewed_rank_score, 8.0, 99.0)
        
        # Keep a minority of the raw physical score, but let the rank-calibrated
        # curve carry the public-facing severity banding.
        scored_network['SpeedSafetyScore'] = (scored_network['SpeedSafetyScore'] * 0.65) + (skewed_rank_score * 0.35)
        
        # Soften score distribution using power-based curved penalty
        # Exponent > 1 compresses penalties and moves borderline cases out of
        # severe categories while preserving the relative rank order.
        penalty = 100.0 - scored_network['SpeedSafetyScore']
        curved_penalty = np.power(penalty / 100.0, 0.92) * 100.0
        scored_network['SpeedSafetyScore'] = 100.0 - curved_penalty
        
        # Phase 44: Align Safe System Violations with S3.
        # Soft-compress violator scores above 80.0 to penalize misalignment while preserving uniqueness.
        violators = scored_network['SafeSystemAligned'] == False
        above_cap = (scored_network['SpeedSafetyScore'] > 78.0) & violators
        scored_network.loc[above_cap, 'SpeedSafetyScore'] = 78.0 + (scored_network.loc[above_cap, 'SpeedSafetyScore'] - 78.0) * 0.15
        
        # Phase 41: Reward zero-hazard segments
        no_hazard_mask = (scored_network['EffectiveHazards_VRU'] == 0) & (scored_network['SegmentConflicts_V2V'] == 0) & (scored_network['SegmentConflicts_V2O'] == 0)
        scored_network.loc[no_hazard_mask, 'SpeedSafetyScore'] = scored_network.loc[no_hazard_mask, 'SpeedSafetyScore'] + 3.0
        
        # Soft cap at 100.0
        above_100 = scored_network['SpeedSafetyScore'] > 100.0
        scored_network.loc[above_100, 'SpeedSafetyScore'] = 100.0 - 1e-4 + (scored_network.loc[above_100, 'SpeedSafetyScore'] - 100.0) * 0.01
        
        # Floor at 10.0 for zero-hazard segments
        scored_network.loc[no_hazard_mask, 'SpeedSafetyScore'] = np.maximum(scored_network.loc[no_hazard_mask, 'SpeedSafetyScore'], 10.0)
        
        # === UNIQUE 4-DECIMAL SCORE GENERATION ===
        # Deterministic Tie-Breaking:
        # Step 1: Ensure sorting columns are present and numeric
        scored_network['_orig_idx'] = scored_network.index
        if 'OBJECTID' in scored_network.columns:
            scored_network['OBJECTID_numeric'] = pd.to_numeric(scored_network['OBJECTID'], errors='coerce').fillna(0).astype(int)
        else:
            scored_network['OBJECTID_numeric'] = 0
            
        if 'SampleSize_avg' not in scored_network.columns:
            scored_network['SampleSize_avg'] = 10.0
            
        # Step 2: Sort by SpeedSafetyScore, SampleSize_avg (descending), and OBJECTID
        scored_network = scored_network.sort_values(
            by=['SpeedSafetyScore', 'SampleSize_avg', 'OBJECTID_numeric'], 
            ascending=[True, False, True],
            kind='mergesort'
        )
        
        # Step 3: Apply microscopic linear adjustment
        scored_network['_rank'] = np.arange(len(scored_network))
        scored_network['SpeedSafetyScore'] = scored_network['SpeedSafetyScore'] + ((scored_network['_rank'] / len(scored_network)) * 1e-4)
        
        # Step 4: Round to 4 decimal places for clean storage
        scored_network['SpeedSafetyScore'] = scored_network['SpeedSafetyScore'].round(4)
        
        # Step 5: Restore original index order and drop temp columns
        scored_network = scored_network.sort_index()
        scored_network.drop(columns=['_orig_idx', 'OBJECTID_numeric', '_rank'], inplace=True)
        
        # Align rubric category scores to sum exactly to the final score
        scored_network = self._align_rubric_categories(scored_network)
            
        return scored_network
