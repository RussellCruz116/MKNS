import os
import sys
import sqlite3
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from dotenv import load_dotenv

# Set paths
base_dir = r"C:\Users\Johan\OneDrive\Documents\ADB\makenes_project"
sys.path.append(os.path.join(base_dir, 'prototypes'))
sys.path.append(base_dir)

load_dotenv(os.path.join(base_dir, '.env'))

from prototypes.data_enrichment.spatial_enricher import SpatialEnricher
from prototypes.speed_safety_score.score_calculator import SpeedSafetyScoreCalculator
from agents.database_manager import DatabaseManager

def main():
    geojson_path = os.path.join(base_dir, 'makenes_scored.geojson')
    db_path = os.path.join(base_dir, 'db', 'makenes.sqlite')
    
    print("1. Loading scored network GeoJSON...")
    if not os.path.exists(geojson_path):
        print(f"Error: {geojson_path} does not exist.")
        sys.exit(1)
        
    network = gpd.read_file(geojson_path)
    network['OBJECTID'] = pd.to_numeric(network['OBJECTID'], errors='coerce').fillna(0).astype(int)
    network['SpeedSafetyScore'] = pd.to_numeric(network['SpeedSafetyScore'], errors='coerce')
    network['Mapillary_Crosswalks'] = pd.to_numeric(network['Mapillary_Crosswalks'], errors='coerce').fillna(0).astype(int)
    
    print(f"Loaded network with {len(network)} segments.")
    
    # 2. Use the entire road network for enrichment
    print("2. Preparing to enrich the entire 69k road network...")
    subset = network.copy()
    
    # 3. Instantiate SpatialEnricher and override cache checks for targeted columns
    print("3. Initializing SpatialEnricher with bypassed SQLite cache checks for OSM and Mapillary...")
    enricher = SpatialEnricher(base_dir, country=None)
    
    original_is_cached = enricher._is_cached
    
    # We want to force queries for OSM and Mapillary columns even if they are currently cached (or 0)
    osm_cols = [
        'POI_Schools_500m', 'POI_Hospitals_500m', 'POI_Markets_500m', 'POI_Transit_500m',
        'OSM_Cycleways_500m', 'OSM_Sidewalks_500m', 'OSM_Crossings_500m'
    ]
    mapillary_cols = ['Mapillary_TrafficSigns', 'Mapillary_Crosswalks']
    target_cols = osm_cols + mapillary_cols
    
    def custom_is_cached(gdf, columns):
        if any(col in columns for col in target_cols):
            # Bypass cache, force query
            return False
        return original_is_cached(gdf, columns)
        
    enricher._is_cached = custom_is_cached
    
    # Run the enrichment on the entire network with multiple attempts to handle Overpass timeouts/rate limits
    print("Running targeted SpatialEnricher on the entire network...")
    attempts = 0
    max_attempts = 4
    enriched_subset = subset
    
    while attempts < max_attempts:
        print(f"\n--- Enrichment Attempt {attempts + 1} of {max_attempts} ---")
        try:
            enriched_subset = enricher.enrich(subset)
            print(f"Attempt {attempts + 1} finished successfully.")
        except Exception as e:
            print(f"Attempt {attempts + 1} encountered an exception: {e}")
        attempts += 1
    
    # 4. Merge back to main network
    print("4. Merging enriched subset back into the global network...")
    network.set_index('OBJECTID', inplace=True, drop=False)
    enriched_subset.set_index('OBJECTID', inplace=True, drop=False)
    
    cols_to_update = [
        'POI_Schools_500m', 'POI_Hospitals_500m', 'POI_Markets_500m', 'POI_Transit_500m',
        'OSM_Cycleways_500m', 'OSM_Sidewalks_500m', 'OSM_Crossings_500m', 'OSM_TrafficCalming_500m',
        'OSM_StreetLighting_500m', 'OSM_Barriers_500m', 'OSM_RoadSurface', 'OSM_LaneCount',
        'OSM_MaxSpeed', 'OSM_LandUse', 'Mapillary_TrafficSigns', 'Mapillary_Crosswalks'
    ]
    
    for col in cols_to_update:
        if col in enriched_subset.columns:
            # Reindex and convert types correctly
            series = enriched_subset[col]
            if col in network.columns:
                target_dtype = network[col].dtype
                if pd.api.types.is_numeric_dtype(series):
                    series = series.fillna(0).astype(target_dtype)
                else:
                    series = series.fillna('').astype(target_dtype)
            else:
                if pd.api.types.is_numeric_dtype(series):
                    series = series.fillna(0).astype(int)
                else:
                    series = series.fillna('').astype(str)
            network.loc[enriched_subset.index, col] = series
            
    network.reset_index(drop=True, inplace=True)
    
    # 5. Recalculate scores so the new infrastructure counts are reflected
    print("5. Recalculating scores with updated infrastructure context...")
    db_manager = DatabaseManager(db_path)
    conn = db_manager.get_connection()
    
    # Load conflicts and pets
    try:
        conflicts_df = pd.read_sql_query("SELECT * FROM abm_conflicts_global", conn)
        conflicts = conflicts_df.to_dict('records')
        pets = conflicts_df[conflicts_df['type'] == 'PET'].to_dict('records')
        print(f"Loaded {len(conflicts)} conflicts and {len(pets)} pets from database.")
    except Exception as e:
        print(f"Error loading conflicts from DB: {e}. Defaulting to empty lists.")
        conflicts = []
        pets = []
    finally:
        conn.close()
        
    # Infer supervisor
    default_supervisor = "thailand_supervisor.md"
    if 'SubSupervisorID' in network.columns:
        most_common = network['SubSupervisorID'].mode()
        if not most_common.empty:
            if 'india' in str(most_common.iloc[0]).lower():
                default_supervisor = "maharashtra_supervisor.md"
            elif 'thailand' in str(most_common.iloc[0]).lower():
                default_supervisor = "thailand_supervisor.md"

    supervisor_path = os.path.join(base_dir, 'agents', 'supervisors', default_supervisor)
    if os.path.exists(supervisor_path):
        print(f"Instantiating Supervisor: {default_supervisor}")
        from prototypes.analytical_model.regional_guides import AgenticSupervisor
        real_guide = AgenticSupervisor(supervisor_path, network_gdf=network)
    else:
        print(f"Supervisor path {supervisor_path} not found. Using dummy guide.")
        class DummyGuide:
            def __init__(self):
                self.params = {}
        real_guide = DummyGuide()
        
    calc = SpeedSafetyScoreCalculator(network, conflicts, pets, [], real_guide, sim_steps=50)
    network = calc.compute_scores()
    
    # 6. Save back to GeoJSON and Database
    print("6. Saving updated network back to GeoJSON and SQLite...")
    network.to_file(geojson_path, driver='GeoJSON')
    db_manager.store_network(network, table_name="scored_network_global")
    
    # Synthesize Ministerial Report
    print("7. Re-generating Ministerial Report...")
    try:
        from prototypes.analytical_model.ministerial_orchestrator import MinisterialOrchestrator
        orchestrator = MinisterialOrchestrator(network, base_dir)
        orchestrator.generate_report()
    except Exception as e:
        print(f"Failed to generate report: {e}")
        
    print("Targeted subset enrichment complete!")

if __name__ == "__main__":
    main()
