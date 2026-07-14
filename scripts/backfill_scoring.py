import os
import sqlite3
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from agents.database_manager import DatabaseManager


SCORE_COLUMNS = [
    "Score_Kinematics",
    "Score_Friction",
    "Score_VRU",
    "Score_Speeding",
    "Score_AI",
    "Score_Stress",
]

MAX_COLUMNS = [
    "Max_Kinematics",
    "Max_Friction",
    "Max_VRU",
    "Max_Speeding",
    "Max_AI",
    "Max_Stress",
]


def rubric_weights(road_class, speed_limit):
    road_class = str(road_class).lower()
    try:
        speed_limit = float(speed_limit)
    except (TypeError, ValueError):
        speed_limit = 50.0

    if "motorway" in road_class or speed_limit >= 80:
        return [25.0, 25.0, 5.0, 25.0, 15.0, 0.0, 5.0]
    if road_class in {"residential", "living_street", "service"} or speed_limit <= 30:
        return [10.0, 15.0, 20.0, 15.0, 15.0, 15.0, 10.0]
    if speed_limit <= 40:
        return [15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 10.0]
    if road_class in {"trunk", "primary", "secondary"}:
        return [15.0, 15.0, 20.0, 15.0, 15.0, 10.0, 10.0]
    if road_class in {"tertiary", "unclassified"} or speed_limit >= 60:
        return [15.0, 20.0, 10.0, 20.0, 15.0, 10.0, 10.0]
    return [20.0, 15.0, 15.0, 15.0, 15.0, 10.0, 10.0]


def numeric(series, default=0.0):
    if not isinstance(series, pd.Series):
        return default
    return pd.to_numeric(series, errors="coerce").fillna(default)


def apply_phase56(gdf):
    for col in SCORE_COLUMNS + MAX_COLUMNS:
        if col not in gdf.columns:
            gdf[col] = 0.0
        gdf[col] = numeric(gdf[col])

    weights = gdf.apply(lambda row: rubric_weights(row.get("RoadClass"), row.get("SpeedLimit")), axis=1)
    weights_df = pd.DataFrame(
        weights.tolist(),
        columns=MAX_COLUMNS + ["Max_Infrastructure"],
        index=gdf.index,
    )

    old_max = gdf[MAX_COLUMNS].replace(0, np.nan)
    score_ratio = gdf[SCORE_COLUMNS].to_numpy(dtype=float) / old_max.to_numpy(dtype=float)
    score_ratio = np.nan_to_num(score_ratio, nan=0.0, posinf=0.0, neginf=0.0)

    for idx, col in enumerate(SCORE_COLUMNS):
        gdf[col] = np.clip(score_ratio[:, idx], 0.0, 1.0) * weights_df[MAX_COLUMNS[idx]]
        gdf[MAX_COLUMNS[idx]] = weights_df[MAX_COLUMNS[idx]]

    # Dynamically calculate infrastructure penalties and bonuses from raw OSM/Mapillary/HeiGIT columns
    infra_bonus = pd.Series(0.0, index=gdf.index)
    infra_penalty = pd.Series(0.0, index=gdf.index)

    if 'OSM_Sidewalks_500m' in gdf.columns:
        sidewalks = pd.to_numeric(gdf['OSM_Sidewalks_500m'], errors='coerce').fillna(0)
        is_urban = gdf.get('LandUse', pd.Series('URBAN', index=gdf.index)).isin(['URBAN', 'urban'])
        speed_limit = pd.to_numeric(gdf.get('SpeedLimit', 50.0), errors='coerce').fillna(50.0)
        no_sidewalk_urban = (sidewalks == 0) & is_urban & (speed_limit <= 60)
        infra_penalty = infra_penalty + np.where(no_sidewalk_urban, 6.0, 0.0)

    if 'OSM_Crossings_500m' in gdf.columns:
        crossings = pd.to_numeric(gdf['OSM_Crossings_500m'], errors='coerce').fillna(0)
        infra_bonus = infra_bonus + np.clip(crossings * 1.0, 0.0, 4.0)

    if 'OSM_TrafficCalming_500m' in gdf.columns:
        calming = pd.to_numeric(gdf['OSM_TrafficCalming_500m'], errors='coerce').fillna(0)
        infra_bonus = infra_bonus + np.clip(calming * 1.5, 0.0, 6.0)

    if 'OSM_StreetLighting_500m' in gdf.columns:
        lighting = pd.to_numeric(gdf['OSM_StreetLighting_500m'], errors='coerce').fillna(0)
        has_lighting = lighting > 0
        infra_bonus = infra_bonus + np.where(has_lighting, np.clip(lighting * 0.6, 0.0, 3.0), 0.0)
        no_light_urban = (~has_lighting) & is_urban if 'OSM_Sidewalks_500m' in gdf.columns else pd.Series(False, index=gdf.index)
        infra_penalty = infra_penalty + np.where(no_light_urban, 4.0, 0.0)

    if 'OSM_Cycleways_500m' in gdf.columns:
        cycleways = pd.to_numeric(gdf['OSM_Cycleways_500m'], errors='coerce').fillna(0)
        infra_bonus = infra_bonus + np.clip(cycleways * 1.0, 0.0, 3.0)

    if 'Mapillary_TrafficSigns' in gdf.columns:
        signs = pd.to_numeric(gdf['Mapillary_TrafficSigns'], errors='coerce').fillna(0)
        infra_bonus = infra_bonus + np.clip(signs * 0.4, 0.0, 4.0)
    if 'Mapillary_Crosswalks' in gdf.columns:
        map_crosswalks = pd.to_numeric(gdf['Mapillary_Crosswalks'], errors='coerce').fillna(0)
        infra_bonus = infra_bonus + np.clip(map_crosswalks * 1.0, 0.0, 4.0)

    surface_penalty = pd.Series(0.0, index=gdf.index)
    if 'OSM_RoadSurface' in gdf.columns:
        is_unpaved = gdf['OSM_RoadSurface'].astype(str).str.lower().isin(['unpaved', 'dirt', 'gravel', 'earth', 'sand', 'grass', 'mud'])
        surface_penalty = surface_penalty + np.where(is_unpaved, 6.0, 0.0)
    if 'OSM_RoadSmoothness' in gdf.columns:
        is_rough = gdf['OSM_RoadSmoothness'].astype(str).str.lower().isin(['bad', 'very_bad', 'rough', 'horrible', 'impassable', 'very_horrible'])
        surface_penalty = surface_penalty + np.where(is_rough, 4.0, 0.0)
        
    infra_penalty = infra_penalty + surface_penalty

    # Save recalculated fields to gdf
    gdf["InfraGapPenalty"] = infra_penalty
    gdf["InfraBonus"] = infra_bonus
    gdf["SurfacePenalty"] = surface_penalty

    infra_raw = np.maximum(0.0, infra_penalty - infra_bonus)
    q99 = float(infra_raw.quantile(0.99)) if len(infra_raw) else 0.0
    if q99 <= float(infra_raw.min() if len(infra_raw) else 0.0):
        q99 = float(infra_raw.max() if len(infra_raw) else 1.0) or 1.0
    infra_norm = np.clip(infra_raw / q99, 0.0, 1.0)

    gdf["I_Infra_raw"] = infra_raw
    gdf["I_Infra_norm"] = infra_norm
    gdf["Max_Infrastructure"] = weights_df["Max_Infrastructure"]
    gdf["Score_Infrastructure"] = gdf["Max_Infrastructure"] * (1.0 - infra_norm)

    raw_total = gdf[SCORE_COLUMNS + ["Score_Infrastructure"]].sum(axis=1).clip(0.0, 100.0)
    gdf["SpeedSafetyScore_PreShipRaw"] = raw_total

    # --- Channel A: Power-law stretch (preserves absolute physics meaning) ---
    power_score = (raw_total / 100.0) ** 1.15 * 100.0

    # --- Channel B: Skewnorm (provides relative context within the distribution) ---
    from scipy.stats import skewnorm
    rank_pct = raw_total.rank(method="first", pct=True).clip(0.0001, 0.9999)
    # Use the original S3 calculator skewnorm values to prevent "too kind" runaway inflation
    skewed_vals = skewnorm.ppf(rank_pct, a=-0.55, loc=66.0, scale=28.0)
    skew_score = np.clip(skewed_vals, 0.0, 100.0)

    # Save components
    gdf["Score_PowerLaw"] = power_score.round(3)
    gdf["Score_SkewNorm"] = skew_score.round(3)

    # --- Blend: 70% power-law (physics-dominant) + 30% skewnorm (distribution-aware) ---
    base_score = (power_score * 0.70 + skew_score * 0.30)
    if 'BonusScore' in gdf.columns:
        base_score += gdf['BonusScore'].fillna(0.0)
        
    gdf["SpeedSafetyScore"] = base_score.clip(0.0, 100.0)

    if "SafeSystemAligned" in gdf.columns:
        violators = gdf["SafeSystemAligned"].astype(str).str.lower().isin(["false", "0"])
        above_cap = (gdf["SpeedSafetyScore"] > 65.0) & violators
        gdf.loc[above_cap, "SpeedSafetyScore"] = 65.0 + (
            gdf.loc[above_cap, "SpeedSafetyScore"] - 65.0
        ) * 0.15

    for col in ["EffectiveHazards_VRU", "SegmentConflicts_V2V", "SegmentConflicts_V2O"]:
        if col not in gdf.columns:
            gdf[col] = 0.0
        gdf[col] = numeric(gdf[col])
    no_hazard = (
        (gdf["EffectiveHazards_VRU"] == 0)
        & (gdf["SegmentConflicts_V2V"] == 0)
        & (gdf["SegmentConflicts_V2O"] == 0)
    )
    above_100 = gdf["SpeedSafetyScore"] > 100.0
    gdf.loc[above_100, "SpeedSafetyScore"] = 100.0 - 1e-4 + (
        gdf.loc[above_100, "SpeedSafetyScore"] - 100.0
    ) * 0.01
    gdf["SpeedSafetyScore"] = gdf["SpeedSafetyScore"].clip(0.0, 100.0).round(3)
    gdf["ScoreCalibration"] = "Hybrid_PL1.15_SN-3.0_70-30"

    # Align rubric category scores to sum exactly to the final score
    categories = {
        'Score_Kinematics': 'Max_Kinematics',
        'Score_Friction': 'Max_Friction',
        'Score_VRU': 'Max_VRU',
        'Score_Speeding': 'Max_Speeding',
        'Score_AI': 'Max_AI',
        'Score_Stress': 'Max_Stress',
        'Score_Infrastructure': 'Max_Infrastructure'
    }
    
    raw_sum = sum(gdf[cat] for cat in categories.keys())
    raw_sum_is_zero = (raw_sum == 0)
    
    if raw_sum_is_zero.any():
        for cat, max_col in categories.items():
            gdf.loc[raw_sum_is_zero, cat] = gdf.loc[raw_sum_is_zero, max_col] * 0.1
        raw_sum = sum(gdf[cat] for cat in categories.keys())
        
    final_score = gdf['SpeedSafetyScore']
    
    under_score = final_score > raw_sum
    over_score = final_score < raw_sum
    
    # Case 1: final_score < raw_sum
    factor = np.where(raw_sum > 0, final_score / raw_sum, 0.0)
    for cat in categories.keys():
        gdf.loc[over_score, cat] = gdf.loc[over_score, cat] * factor[over_score]
        
    # Case 2: final_score > raw_sum
    total_room = sum(gdf[max_col] - gdf[cat] for cat, max_col in categories.items())
    total_room = np.where(total_room > 0, total_room, 1.0)
    
    for cat, max_col in categories.items():
        room = gdf[max_col] - gdf[cat]
        gdf.loc[under_score, cat] = gdf.loc[under_score, cat] + (final_score[under_score] - raw_sum[under_score]) * (room[under_score] / total_room[under_score])
        
    for cat, max_col in categories.items():
        gdf[cat] = np.clip(gdf[cat], 0.0, gdf[max_col]).round(3)

    return gdf


def main():
    geojson_path = os.path.join(BASE_DIR, "makenes_scored.geojson")
    db_path = os.path.join(BASE_DIR, "db", "makenes.sqlite")

    print(f"Loading {geojson_path}...")
    gdf = gpd.read_file(geojson_path)
    gdf = apply_phase56(gdf)

    print("Writing updated GeoJSON...")
    gdf.to_file(geojson_path, driver="GeoJSON")

    if os.path.exists(db_path):
        print("Writing updated SQLite scored_network_global...")
        DatabaseManager(db_path).store_network(gdf, "scored_network_global")
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM scored_network_global").fetchone()[0]
            print(f"SQLite scored_network_global rows: {count}")

    print(
        "Standard Score summary:",
        gdf["SpeedSafetyScore"].min(),
        gdf["SpeedSafetyScore"].median(),
        gdf["SpeedSafetyScore"].max(),
    )

    whatif_path = os.path.join(BASE_DIR, "makenes_whatif_scored.geojson")
    if os.path.exists(whatif_path):
        print(f"Loading {whatif_path}...")
        gdf_whatif = gpd.read_file(whatif_path)
        gdf_whatif = apply_phase56(gdf_whatif)
        print("Writing updated WhatIf GeoJSON...")
        gdf_whatif.to_file(whatif_path, driver="GeoJSON")
        print(
            "WhatIf Score summary:",
            gdf_whatif["SpeedSafetyScore"].min(),
            gdf_whatif["SpeedSafetyScore"].median(),
            gdf_whatif["SpeedSafetyScore"].max(),
        )


if __name__ == "__main__":
    main()
