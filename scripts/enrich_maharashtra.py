import os
import sys
import pandas as pd
import geopandas as gpd
from dotenv import load_dotenv

base_dir = r"C:\Users\Johan\OneDrive\Documents\ADB\makenes_project"
sys.path.append(os.path.join(base_dir, 'prototypes'))
sys.path.append(base_dir)

load_dotenv(os.path.join(base_dir, '.env'))

from prototypes.data_enrichment.spatial_enricher import SpatialEnricher

def main():
    geojson_path = os.path.join(base_dir, 'maharashtra_scored.geojson')
    if not os.path.exists(geojson_path):
        print(f"Error: {geojson_path} does not exist. Please wait for the filter script to finish.")
        sys.exit(1)
        
    print("1. Loading Maharashtra network GeoJSON...")
    network = gpd.read_file(geojson_path)
    print(f"Loaded Maharashtra network with {len(network)} segments.")
    
    print("2. Initializing SpatialEnricher for India...")
    # Initialize for India to force the new PyOsmium dynamic loading
    enricher = SpatialEnricher(base_dir, country='india')
    
    original_is_cached = enricher._is_cached
    osm_cols = [
        'POI_Schools_500m', 'POI_Hospitals_500m', 'POI_Markets_500m', 'POI_Transit_500m',
        'OSM_Cycleways_500m', 'OSM_Sidewalks_500m', 'OSM_Crossings_500m'
    ]
    mapillary_cols = ['Mapillary_TrafficSigns', 'Mapillary_Crosswalks']
    target_cols = osm_cols + mapillary_cols
    
    def custom_is_cached(gdf, columns):
        if any(col in columns for col in target_cols):
            return False
        return original_is_cached(gdf, columns)
        
    enricher._is_cached = custom_is_cached
    
    print("3. Running SpatialEnricher on Maharashtra network...")
    try:
        enriched_subset = enricher.enrich(network)
        print("Enrichment finished successfully.")
        
        out_path = os.path.join(base_dir, 'maharashtra_scored_enriched.geojson')
        enriched_subset.to_file(out_path, driver='GeoJSON')
        print(f"Saved to {out_path}")
    except Exception as e:
        print(f"Enrichment encountered an exception: {e}")

if __name__ == '__main__':
    main()
