import os
import sys
import pandas as pd
import geopandas as gpd
import sqlite3

base_dir = r"C:\Users\Johan\OneDrive\Documents\ADB\makenes_project"
sys.path.append(os.path.join(base_dir, 'prototypes'))
sys.path.append(base_dir)

from prototypes.data_enrichment.spatial_enricher import SpatialEnricher
from agents.database_manager import DatabaseManager

def main():
    geojson_path = os.path.join(base_dir, 'makenes_scored.geojson')
    if not os.path.exists(geojson_path):
        print(f"Error: {geojson_path} does not exist.")
        sys.exit(1)
        
    print("1. Loading global network GeoJSON...")
    global_net = gpd.read_file(geojson_path)
    print(f"Loaded global network with {len(global_net)} segments.")
    
    # Filter Maharashtra segments
    maharashtra_mask = global_net['SubSupervisorID'].astype(str).str.lower().str.startswith('maharashtra')
    maharashtra_net = global_net[maharashtra_mask].copy()
    thailand_net = global_net[~maharashtra_mask].copy()
    
    print(f"Maharashtra segments: {len(maharashtra_net)}")
    print(f"Thailand segments: {len(thailand_net)}")
    
    print("2. Initializing SpatialEnricher for Maharashtra (India)...")
    enricher = SpatialEnricher(base_dir, country='india')
    enricher._detected_country = 'india'
    
    # Force enrich even if cached columns exist to recalculate without inflation
    original_is_cached = enricher._is_cached
    osm_cols = [
        'POI_Schools_500m', 'POI_Hospitals_500m', 'POI_Markets_500m', 'POI_Transit_500m',
        'OSM_Cycleways_500m', 'OSM_Sidewalks_500m', 'OSM_Crossings_500m', 'OSM_StreetLighting_500m',
        'OSM_TrafficCalming_500m', 'OSM_Barriers_500m', 'OSM_RoadSurface', 'OSM_LaneCount',
        'OSM_MaxSpeed', 'OSM_LandUse'
    ]
    
    def custom_is_cached(gdf, columns):
        if any(col in columns for col in osm_cols):
            return False
        return original_is_cached(gdf, columns)
        
    enricher._is_cached = custom_is_cached
    
    print("3. Running SpatialEnricher on Maharashtra network (parsing local India PBF)...")
    try:
        # Run only the OSM enrichment step
        enriched_maharashtra = enricher._safe_run('OSM Overpass POIs', enricher._enrich_osm_pois, maharashtra_net)
        
        # Merge back (keep Thailand segments untouched)
        final_net = gpd.GeoDataFrame(pd.concat([thailand_net, enriched_maharashtra], ignore_index=True), crs=global_net.crs)
        
        print("4. Saving updated global network to GeoJSON...")
        final_net.to_file(geojson_path, driver='GeoJSON')
        
        print("5. Updating SQLite scored_network_global table...")
        db_manager = DatabaseManager(os.path.join(base_dir, 'db', 'makenes.sqlite'))
        db_manager.store_network(final_net, table_name="scored_network_global")
        
        print("Maharashtra enrichment finished successfully!")
        
    except Exception as e:
        print(f"Enrichment failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
