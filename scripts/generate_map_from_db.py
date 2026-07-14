import os
import sys
import geopandas as gpd
import pandas as pd
from shapely import wkt
import sqlite3

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(base_dir)

from prototypes.geospatial_model.map_generator import MapGenerator

db_path = os.path.join(base_dir, 'db', 'makenes.sqlite')
conn = sqlite3.connect(db_path)

print("Loading scored network from SQLite...")
df_network = pd.read_sql_query("SELECT * FROM scored_network_global", conn)
df_network['geometry'] = df_network['geometry_wkt'].apply(wkt.loads)
gdf_network = gpd.GeoDataFrame(df_network, geometry='geometry', crs="EPSG:4326")

print("Loading ABM conflicts from SQLite...")
df_conflicts = pd.read_sql_query("SELECT * FROM abm_conflicts_global", conn)
df_conflicts['geometry'] = df_conflicts['geometry_wkt'].apply(wkt.loads)
gdf_conflicts = gpd.GeoDataFrame(df_conflicts, geometry='geometry', crs="EPSG:4326")

print(f"Generating Unified MapLibre GL Dashboard for {len(gdf_network)} segments and {len(gdf_conflicts)} ABM events...")
map_gen = MapGenerator(gdf_network, conflict_gdf=gdf_conflicts)
output_html = os.path.join(base_dir, 'makenes_safety_map.html')
output_geojson = os.path.join(base_dir, 'makenes_scored.geojson')
map_gen.generate_map(output_html=output_html, output_geojson=output_geojson)

print(f"Success! Map written to {output_html}")
