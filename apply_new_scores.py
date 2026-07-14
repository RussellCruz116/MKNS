import os
import sys
import sqlite3
import argparse
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# Ensure prototypes is in path
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(base_dir, 'prototypes'))
sys.path.append(base_dir)

# --- CLI Arguments ---
parser = argparse.ArgumentParser(description='MaKeNeS Full Pipeline: Score + Enrich + Map')
parser.add_argument('--country', type=str, default=None,
                    help='Country name or ISO code (e.g., "india", "thailand", "IND", "THA"). '
                         'Auto-detected from network geometry if not provided.')
parser.add_argument('--skip-enrichment', action='store_true',
                    help='Skip spatial data enrichment (faster, uses cached columns if present).')
args = parser.parse_args()

from prototypes.speed_safety_score.score_calculator import SpeedSafetyScoreCalculator
from prototypes.geospatial_model.map_generator import MapGenerator
from prototypes.analytical_model.abm_engine import MaKeNeSABM
from agents.database_manager import DatabaseManager

geojson_path = os.path.join(base_dir, 'makenes_scored.geojson')
db_path = os.path.join(base_dir, 'db', 'makenes.sqlite')

print("1. Loading scored network...")
network = gpd.read_file(geojson_path)

if 'LandUse' not in network.columns:
    print("    [Warning] LandUse missing from GeoJSON. Restoring from raw database networks...")
    conn = sqlite3.connect(db_path)
    raw_thai = pd.read_sql_query("SELECT OBJECTID, LandUse FROM raw_network_thailand", conn)
    raw_maha = pd.read_sql_query("SELECT OBJECTID, LandUse FROM raw_network_maharashtra", conn)
    raw_all = pd.concat([raw_thai, raw_maha]).drop_duplicates(subset=['OBJECTID'])
    # Align type of OBJECTID to string for merging
    network['OBJECTID'] = network['OBJECTID'].astype(str)
    raw_all['OBJECTID'] = raw_all['OBJECTID'].astype(str)
    
    # Drop any existing LandUse column just in case to prevent duplicates
    if 'LandUse' in network.columns:
        network = network.drop(columns=['LandUse'])
    network = network.merge(raw_all, on='OBJECTID', how='left')
    conn.close()

# --- Spatial Data Enrichment ---
if not args.skip_enrichment:
    print("2a. Enriching network with spatial datasets (GHS-POP, Buildings, UCDB, ATO, OSM POIs, Mapillary)...")
    try:
        from prototypes.data_enrichment.spatial_enricher import SpatialEnricher
        enricher = SpatialEnricher(base_dir, country=args.country)
        network = enricher.enrich(network)
        print("    Enrichment complete.")
    except ImportError as e:
        print(f"    WARN: Enrichment skipped — missing dependency: {e}")
        print("    Install with: pip install rasterstats rasterio openpyxl pyproj")
    except Exception as e:
        print(f"    WARN: Enrichment failed (non-fatal): {e}")
else:
    print("2a. Skipping enrichment (--skip-enrichment flag).")

print("2a-1. Imputing and cleaning dataset using DataCleaner...")
from prototypes.data_enrichment.data_cleaner import DataCleaner
cleaner = DataCleaner(country=args.country)
network = cleaner.clean(network)

print("2b. Connecting to SQLite and loading conflicts/pets...")
db_manager = DatabaseManager(db_path)
conn = db_manager.get_connection()

# Load conflicts and pets
try:
    conflicts_df = pd.read_sql_query("SELECT * FROM abm_conflicts_global", conn)
    conflicts = conflicts_df.to_dict('records')
    # Filter for PET type specifically
    pets = conflicts_df[conflicts_df['type'] == 'PET'].to_dict('records')
except Exception as e:
    print(f"Error loading conflicts from DB: {e}. Defaulting to empty lists.")
    conflicts = []
    pets = []

print("3. Recalculating scores with real Regional AI Supervisor context...")
from prototypes.analytical_model.regional_guides import AgenticSupervisor

# Infer supervisor from the most common SubSupervisorID
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
    print(f"   -> Instantiating Real Supervisor: {default_supervisor}")
    real_guide = AgenticSupervisor(supervisor_path, network_gdf=network)
else:
    print(f"   -> Supervisor {default_supervisor} not found. Falling back to DummyGuide.")
    class DummyGuide:
        def __init__(self):
            self.params = {}
    real_guide = DummyGuide()

calc = SpeedSafetyScoreCalculator(network, conflicts, pets, [], real_guide, sim_steps=300, baseline_steps=43200)
network = calc.compute_scores()

print("3b. Applying Phase 56 Scoring Recalibration...")
from scripts.backfill_scoring import apply_phase56
network = apply_phase56(network)

print("4. Saving updated GeoJSON and DB table...")
network.to_file(geojson_path, driver='GeoJSON')
db_manager.store_network(network, table_name="scored_network_global")

print("5. Synthesizing AI Swarm outputs into Ministerial Report...")
from prototypes.analytical_model.ministerial_orchestrator import MinisterialOrchestrator
orchestrator = MinisterialOrchestrator(network, base_dir)
orchestrator.generate_report()

print("6. Triggering Lifecycle Hooks...")
hook_path = os.path.join(base_dir, 'hooks', 'post_analytics.py')
os.system(f"{sys.executable} {hook_path} \"{geojson_path}\"")

print("7. Training ML Extrapolator and running What-If scenario...")
from prototypes.analytical_model.ml_extrapolator import train_s3_extrapolator, run_whatif_scenario
out_model = os.path.join(base_dir, 'models', 's3_rf_model.pkl')
out_whatif = os.path.join(base_dir, 'makenes_whatif_scored.geojson')
os.makedirs(os.path.dirname(out_model), exist_ok=True)
train_s3_extrapolator(geojson_path, out_model)
run_whatif_scenario(geojson_path, out_model, out_whatif)

print("8. Generating video frames for the new top 5 segments...")
network['OBJECTID'] = pd.to_numeric(network['OBJECTID'], errors='coerce').fillna(0).astype(int)
top_5_sids = network.sort_values(by='SpeedSafetyScore', ascending=True).head(5)['OBJECTID'].values

# Build Network Topology for 1-hop neighbor loading
print("   Building Network Topology for 1-hop neighbor loading...")
from prototypes.analytical_model.network_topology import NetworkTopology
topology = NetworkTopology(network)

neighbor_sids = set()
for sid in top_5_sids:
    neighbor_sids.update(topology.get_neighbors(sid))

# We simulate both the top 5 segments and their 1-hop neighbors
replay_sids = set(top_5_sids) | neighbor_sids
top_5_segments = network[network['OBJECTID'].isin(replay_sids)]

all_frame_logs = {}
if not top_5_segments.empty:
    ptw_ratio = getattr(real_guide, 'default_ptw_ratio', 0.65)
    abm = MaKeNeSABM(top_5_segments, topology=topology, ptw_ratio=ptw_ratio)
    # Fast-path cache: skip 13-minute ABM if we already have the 43200-tick frame output
    cache_file = os.path.join(base_dir, 'docs', 'frame_data.json')
    if os.path.exists(cache_file):
        print("   Loading existing frame logs from docs/frame_data.json to skip heavy simulation...")
        import json
        with open(cache_file, 'r') as f:
            all_frame_logs = json.load(f)
        # Convert string keys back to int
        all_frame_logs = {int(k): v for k, v in all_frame_logs.items()}
    else:
        _, _, _, frame_logs = abm.run_simulation(steps=43200, region_id="recovery")
        for frame_idx, frame_data in enumerate(frame_logs):
            for actor in frame_data:
                sid = actor.get('segment_id')
                if sid is not None:
                    sid = int(sid)
                    if sid not in all_frame_logs:
                        all_frame_logs[sid] = {'frames': [], 'shape': []}
                    while len(all_frame_logs[sid]['frames']) <= frame_idx:
                        all_frame_logs[sid]['frames'].append([])
                    all_frame_logs[sid]['frames'][frame_idx].append(actor)

    # Inject LineString geometries
    for idx, row in network.iterrows():
        sid = int(row['OBJECTID'])
        if sid in all_frame_logs and row.geometry:
            coords_list = []
            if row.geometry.geom_type == 'LineString':
                coords_list = list(row.geometry.coords)
            elif row.geometry.geom_type == 'MultiLineString':
                for line in row.geometry.geoms:
                    coords_list.extend(list(line.coords))
            all_frame_logs[sid]['shape'] = coords_list

top_5_frame_logs = {sid: frames for sid, frames in all_frame_logs.items() if sid in top_5_sids}

# Save frame data explicitly to docs/ so chunked dashboard can fetch it
import json
os.makedirs(os.path.join(base_dir, 'docs'), exist_ok=True)
with open(os.path.join(base_dir, 'docs', 'frame_data.json'), 'w') as f:
    json.dump(top_5_frame_logs, f)

# Reload snapped conflicts for maps
conflict_gdf = gpd.GeoDataFrame(columns=['geometry', 'type', 'segment_id'], crs="EPSG:4326")
try:
    df = pd.read_sql_query("SELECT * FROM abm_conflicts_global", conn)
    if not df.empty:
        if 'geometry_wkt' in df.columns:
            df['geometry'] = gpd.GeoSeries.from_wkt(df['geometry_wkt'])
        elif 'geometry' in df.columns:
            df['geometry'] = gpd.GeoSeries.from_wkb(df['geometry'])
        conflict_gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
except Exception as e:
    print("Could not load conflicts for mapping:", e)

print("9. Generating Standard MapLibre Dashboard...")
map_gen = MapGenerator(network, conflict_gdf=conflict_gdf, frame_logs=top_5_frame_logs)
output_html = os.path.join(base_dir, 'makenes_safety_map.html')
map_gen.generate_map(output_html=output_html, output_geojson=geojson_path, external_data=True)

print("10. Generating What-If MapLibre Dashboard...")
whatif_gdf = gpd.read_file(out_whatif)
whatif_map_gen = MapGenerator(whatif_gdf, conflict_gdf=conflict_gdf)
whatif_output_html = os.path.join(base_dir, 'makenes_whatif_safety_map.html')
whatif_map_gen.generate_map(output_html=whatif_output_html, output_geojson=out_whatif, external_data=True)

print("11. Generating Chunked Dashboard (docs/index.html & optimized GeoJSON)...")
dashboard_script = os.path.join(base_dir, 'scripts', 'generate_chunked_dashboard.py')
docs_dir = os.path.join(base_dir, 'docs')
os.system(f"{sys.executable} {dashboard_script} --scored-geojson \"{geojson_path}\" --docs-dir \"{docs_dir}\"")

print("All scoring updates applied and dashboards regenerated successfully!")
conn.close()
