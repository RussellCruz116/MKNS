import sys
import os
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prototypes.analytical_model.regional_guides import AgenticSupervisor
from prototypes.analytical_model.abm_engine import MaKeNeSABM
from prototypes.speed_safety_score.score_calculator import SpeedSafetyScoreCalculator
from prototypes.geospatial_model.map_generator import MapGenerator
from prototypes.data_enrichment.spatial_enricher import SpatialEnricher
from prototypes.analytical_model.agent_swarm import AgentSwarm
from prototypes.analytical_model.network_topology import NetworkTopology
from agents.data_orchestrator import DataOrchestrator
from agents.database_manager import DatabaseManager

def process_sub_region(sub, supervisor_file, subsupervisors_dir, sim_mode='rush_hour', steps=100):
    try:
        from prototypes.analytical_model.regional_guides import AgenticSupervisor
        from prototypes.analytical_model.abm_engine import MaKeNeSABM
        from prototypes.speed_safety_score.score_calculator import SpeedSafetyScoreCalculator
        import os
        from shapely.geometry import Point
        import pandas as pd
        
        print(f"\n  ---> Activating Sub-Supervisor: {sub['label']} (Cluster {sub['cluster_id']})")
        sub_agent_path = os.path.join(subsupervisors_dir, sub['persona_file'])
        sub_supervisor = AgenticSupervisor(sub_agent_path, network_gdf=sub['gdf'])
        sub_network_gdf = sub_supervisor.load_network().copy()
        
        print(f"       [{sub['label']}] Running Agent-Based Model (Kinematics & SFM, mode={sim_mode}, steps={steps})...")
        region_id = f"{supervisor_file.split('_')[0]}_Cluster{sub['cluster_id']}_{sub['label']}"
        abm = MaKeNeSABM(sub_network_gdf, topology=sub.get('topology'), ptw_ratio=sub_supervisor.default_ptw_ratio, 
                         seed=42 if os.environ.get("MAKENES_DETERMINISTIC") else None,
                         sim_mode=sim_mode)
        conflict_logs, pet_logs, stress_logs, frame_logs = abm.run_simulation(steps=steps, region_id=region_id)
        
        frame_logs_dict = {}
        for frame_idx, frame_data in enumerate(frame_logs):
            for actor in frame_data:
                sid = actor.get('segment_id')
                if sid is not None:
                    if sid not in frame_logs_dict:
                        frame_logs_dict[sid] = []
                    while len(frame_logs_dict[sid]) <= frame_idx:
                        frame_logs_dict[sid].append([])
                    frame_logs_dict[sid][frame_idx].append(actor)
        
        print(f"       [{sub['label']}] Calculating S3 Scores & AI Speed Interventions...")
        score_calc = SpeedSafetyScoreCalculator(sub_network_gdf, conflict_logs, pet_logs, stress_logs, sub_supervisor, sim_steps=steps)
        scored_sub_network = score_calc.compute_scores()
        scored_sub_network['SubSupervisorID'] = region_id
        
        # Fix IPC MemoryError: Only send frames back to main process for the Top 5 most dangerous roads in this cluster
        if 'OBJECTID' in scored_sub_network.columns:
            top_cluster_sids = set(scored_sub_network.sort_values(by='SpeedSafetyScore', ascending=True).head(50)['OBJECTID'].values)
            top_cluster_sids_frames = set(scored_sub_network.sort_values(by='SpeedSafetyScore', ascending=True).head(5)['OBJECTID'].values)
            filtered_frames = {sid: frames for sid, frames in frame_logs_dict.items() if sid in top_cluster_sids_frames}
        else:
            top_cluster_sids = set()
            filtered_frames = {}
            
        conflict_points = []
        filtered_conflicts = [c for c in conflict_logs if c.get('segment_id') in top_cluster_sids]
        filtered_pets = [p for p in pet_logs if p.get('segment_id') in top_cluster_sids]
        
        import random
        sampled_conflicts = random.sample(filtered_conflicts, 5000) if len(filtered_conflicts) > 5000 else filtered_conflicts
        for conflict in sampled_conflicts:
            loc = conflict['location']
            conflict_points.append({
                'geometry': Point(loc[0], loc[1]), 
                'type': conflict.get('type'),
                'segment_id': conflict.get('segment_id')
            })
            
        sampled_pets = random.sample(filtered_pets, 5000) if len(filtered_pets) > 5000 else filtered_pets
        for pet in sampled_pets:
            loc = pet['location']
            conflict_points.append({
                'geometry': Point(loc[0], loc[1]), 
                'type': 'PET',
                'segment_id': pet.get('segment_id')
            })
            
        return {
            'scored_network': scored_sub_network,
            'conflict_points': conflict_points,
            'frame_logs': filtered_frames
        }
    except Exception as e:
        import traceback
        print(f"Failed in Sub-Region {sub.get('label')}: {e}")
        traceback.print_exc()
        return None

def main():
    load_dotenv()
    from prototypes.reproducibility import is_deterministic, set_deterministic
    if is_deterministic():
        set_deterministic()
        print("[MaKeNeS] Deterministic mode enabled (fixed ABM seeds + LLM cache).")
    print("--- MaKeNeS Full Pipeline ---")
    
    import argparse
    parser = argparse.ArgumentParser(description="MaKeNeS Full Pipeline Orchestrator")
    parser.add_argument("--skip-enrichment", action="store_true", help="Skip spatial/Mapillary enrichment and load from DB table scored_network_global")
    parser.add_argument("--sim-mode", type=str, default="rush_hour", choices=["rush_hour", "full_day"], help="ABM simulation volume mode")
    parser.add_argument("--steps", type=int, default=None, help="Force specific step count (defaults: 100 for rush_hour, 960 for full_day)")
    args = parser.parse_args()
    
    if args.steps is None:
        args.steps = 960 if args.sim_mode == "full_day" else 100
        
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw_dir = os.path.join(base_dir, 'data', 'raw')
    supervisors_dir = os.path.join(base_dir, 'agents', 'supervisors')
    subsupervisors_dir = os.path.join(supervisors_dir, 'sub_supervisors')
    
    db_path = os.path.join(base_dir, 'db', 'makenes.sqlite')
    db_manager = DatabaseManager(db_path)
    
    datasets = {
        "ADB_Innovation_Thailand.geojson": "thailand_supervisor.md",
        "ADB_Innovation_Maharashtra.geojson": "maharashtra_supervisor.md"
    }
    
    all_scored_networks = []
    all_conflict_points = []
    all_frame_logs = {} # Store trajectory frames per segment
    global_id_counter = 1

    for geojson_file, supervisor_file in datasets.items():
        data_path = os.path.join(raw_dir, geojson_file)
        agent_path = os.path.join(supervisors_dir, supervisor_file)
        country_hint = "thailand" if "Thailand" in geojson_file else "india"
        
        print(f"\n======================================")
        print(f"[Initializing Main Supervisor: {supervisor_file}]")
        try:
            # 1. Main Supervisor loads the entire regional network
            main_supervisor = AgenticSupervisor(agent_path, data_path)
            
            skip_e = args.skip_enrichment
            if skip_e:
                # Load from database scored_network_global
                print(f"Loading cached/enriched network from DB for {country_hint}...")
                with db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scored_network_global'")
                    table_exists = cursor.fetchone() is not None
                
                if table_exists:
                    full_network = db_manager.load_network("scored_network_global")
                    if country_hint == "thailand":
                        full_network_gdf = full_network[full_network.geometry.centroid.x > 90].copy()
                    else:
                        full_network_gdf = full_network[full_network.geometry.centroid.x <= 90].copy()
                    print(f"Loaded {len(full_network_gdf)} segments from SQLite database.")
                else:
                    print("scored_network_global table not found in DB! Falling back to raw GeoJSON + full enrichment...")
                    skip_e = False
                    
            if not skip_e:
                if not os.path.exists(data_path):
                    print(f"Skipping {geojson_file}: File not found.")
                    continue
                full_network_gdf = main_supervisor.load_network().copy()
                
                # Assign globally unique OBJECTID to avoid overlaps
                full_network_gdf['OBJECTID'] = range(global_id_counter, global_id_counter + len(full_network_gdf))
                global_id_counter += len(full_network_gdf)

                print(f"Enriching {geojson_file} with additional spatial datasets...")
                enricher = SpatialEnricher(base_dir, country=country_hint)
                full_network_gdf = enricher.enrich(full_network_gdf)
                
                db_manager.store_network(full_network_gdf, table_name=f"raw_network_{supervisor_file.split('_')[0]}")
                
                # --- Mapillary Data Orchestration ---
                orchestrator = DataOrchestrator(full_network_gdf)
                full_network_gdf = orchestrator.inject_mapillary_friction()
            
            # Build Network Topology for this region
            print(f"Building Network Topology for {geojson_file}...")
            topology = NetworkTopology(full_network_gdf)

            # 2. Main Supervisor delegates to Swarm
            swarm = AgentSwarm(main_supervisor, full_network_gdf)
            sub_regions = swarm.spawn_sub_supervisors()
            
            # Attach topology to each sub_region
            for sub in sub_regions:
                sub['topology'] = topology
            
            # 3. Process each sub-region with its specific Sub-Supervisor in parallel
            from concurrent.futures import ProcessPoolExecutor, as_completed
            
            print(f"Spawning {len(sub_regions)} parallel Sub-Supervisors...")
            with ProcessPoolExecutor(max_workers=3) as executor:
                futures = []
                for sub in sub_regions:
                    futures.append(executor.submit(process_sub_region, sub, supervisor_file, subsupervisors_dir, args.sim_mode, args.steps))
                
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        sub_id = result['scored_network']['SubSupervisorID'].iloc[0] if not result['scored_network'].empty else "Unknown"
                        all_scored_networks.append(result['scored_network'])
                        
                        # Store conflict points with SubSupervisorID attached so we can remap them later
                        for cp in result['conflict_points']:
                            cp['SubSupervisorID'] = sub_id
                            all_conflict_points.append(cp)
                            
                        # Store frame logs with (SubSupervisorID, sid) tuple to prevent overwrites
                        for sid, frames in result['frame_logs'].items():
                            all_frame_logs[(sub_id, sid)] = frames
            
        except Exception as e:
            import traceback
            print(f"Failed to process {geojson_file}: {e}")
            traceback.print_exc()
 
    if not all_scored_networks:
        print("No datasets were successfully processed.")
        return
 
    # Merge all sub-regional networks into a single global dataset
    print("\nMerging Sub-Supervisor outputs into Global Map...")
    global_network = pd.concat(all_scored_networks, ignore_index=True)
    
    # Phase 56 Fix: Reassign globally unique OBJECTIDs
    global_network['OLD_OBJECTID'] = global_network['OBJECTID'].copy()
    global_network['OBJECTID'] = range(1, len(global_network) + 1)
    
    # Create mapping from SubSupervisorID and OLD_OBJECTID to NEW_OBJECTID
    id_mapping = {}
    for idx, row in global_network.iterrows():
        id_mapping[(row['SubSupervisorID'], row['OLD_OBJECTID'])] = row['OBJECTID']
        
    # Remap frame logs keys
    new_frame_logs = {}
    for (sub_id, old_sid), frames in all_frame_logs.items():
        if (sub_id, old_sid) in id_mapping:
            new_sid = id_mapping[(sub_id, old_sid)]
            new_frame_logs[new_sid] = frames
    
    # Save frame logs using new mappings
    docs_dir = os.path.join(base_dir, 'docs')
    os.makedirs(docs_dir, exist_ok=True)
    with open(os.path.join(docs_dir, 'abm_frame_logs.json'), "w") as f:
        json.dump(new_frame_logs, f, indent=2)
        
    db_manager.store_network(global_network, table_name="scored_network_global")
    
    # Create GeoDataFrame for conflicts
    if all_conflict_points:
        # Remap segment_id in conflicts
        for cp in all_conflict_points:
            sub_id = cp.get('SubSupervisorID', 'Unknown')
            old_sid = cp.get('segment_id', 0)
            if (sub_id, old_sid) in id_mapping:
                cp['segment_id'] = id_mapping[(sub_id, old_sid)]
                
        # The coordinates extracted from Mesa-Geo points are originally in EPSG:4326 before being passed to MapLibre.
        # abm_engine.py extracts them properly via v_point.x and v_point.y which are from the EPSG:4326 spawn_network.
        conflict_gdf = gpd.GeoDataFrame(all_conflict_points, crs="EPSG:4326")
        
        # Phase 28: Hazard Snapping (snap floating ABM conflicts to the nearest road linestring)
        print("       Snapping floating ABM hazards to nearest road geometries...")
        from shapely.ops import nearest_points
        nearest_indices = global_network.sindex.nearest(conflict_gdf.geometry)[1]
        
        snapped_geoms = []
        for i, pt in enumerate(conflict_gdf.geometry):
            seg_id = conflict_gdf.iloc[i]['segment_id']
            # Find the segment with this OBJECTID
            matching_segments = global_network[global_network['OBJECTID'] == seg_id]
            if not matching_segments.empty:
                nearest_line = matching_segments.iloc[0].geometry
                snapped_pt = nearest_points(pt, nearest_line)[1]
                snapped_geoms.append(snapped_pt)
            else:
                # Fallback to nearest index if segment_id not found
                nearest_line = global_network.iloc[nearest_indices[i]].geometry
                snapped_pt = nearest_points(pt, nearest_line)[1]
                snapped_geoms.append(snapped_pt)
            
        conflict_gdf['geometry'] = snapped_geoms
 
        db_manager.store_conflicts(conflict_gdf, table_name="abm_conflicts_global")
    else:
        conflict_gdf = gpd.GeoDataFrame(columns=['geometry', 'type', 'segment_id'], crs="EPSG:4326")

    # Identify the Top 5 most hazardous roads THAT WERE ACTUALLY SIMULATED to pass their frame logs to the MapGenerator
    # We cap at 5 to prevent massive memory payloads in the browser while still providing enough video evidence.
    global_network['OBJECTID'] = pd.to_numeric(global_network['OBJECTID'], errors='coerce').fillna(0).astype(int)
    simulated_sids = [int(sid) for sid in new_frame_logs.keys()]
    simulated_network = global_network[global_network['OBJECTID'].isin(simulated_sids)]
    if not simulated_network.empty:
        top_5_segments = simulated_network.sort_values(by='SpeedSafetyScore', ascending=True).head(5)['OBJECTID'].values
    else:
        top_5_segments = []
    top_5_frame_logs = {int(sid): frames for sid, frames in new_frame_logs.items() if sid in top_5_segments}

    # Generate unified MapLibre GL Dashboard
    print(f"\nGenerating Unified MapLibre GL Dashboard for {len(global_network)} segments and {len(conflict_gdf)} ABM events...")
    map_gen = MapGenerator(global_network, conflict_gdf=conflict_gdf, frame_logs=top_5_frame_logs)
    output_html = os.path.join(base_dir, 'makenes_safety_map.html')
    output_geojson = os.path.join(base_dir, 'makenes_scored.geojson')
    map_gen.generate_map(output_html=output_html, output_geojson=output_geojson)
    
    # Trigger Master Ministerial Orchestrator
    print("\nSynthesizing AI Swarm outputs into Ministerial Report...")
    from prototypes.analytical_model.ministerial_orchestrator import MinisterialOrchestrator
    orchestrator = MinisterialOrchestrator(global_network, base_dir)
    orchestrator.generate_report()
    
    # 4. Backfill scoring (re-runs the final scoring models safely)
    backfill_path = os.path.join(base_dir, 'scripts', 'backfill_scoring.py')
    print(f"\n--- Running: {backfill_path} ---")
    import subprocess
    subprocess.run([sys.executable, backfill_path], check=True)
    
    hook_path = os.path.join(base_dir, 'hooks', 'post_analytics.py')
    os.system(f"{sys.executable} {hook_path} \"{output_geojson}\"")
    print("----------------------------------\n")

    # ML What-If Extrapolator
    print("\n--- RUNNING WHAT-IF ML SCENARIO ---")
    from prototypes.analytical_model.ml_extrapolator import train_s3_extrapolator, run_whatif_scenario
    
    geojson_path = output_geojson
    out_model = os.path.join(base_dir, 'models', 's3_rf_model.pkl')
    out_whatif = os.path.join(base_dir, 'makenes_whatif_scored.geojson')
    
    os.makedirs(os.path.dirname(out_model), exist_ok=True)
    print("Training ML Extrapolator on current data...")
    train_s3_extrapolator(geojson_path, out_model)
    
    print("Generating What-If Scenario...")
    run_whatif_scenario(geojson_path, out_model, out_whatif)
    
    print("Generating What-If MapLibre Dashboard...")
    whatif_gdf = gpd.read_file(out_whatif)
    whatif_map_gen = MapGenerator(whatif_gdf, conflict_gdf=conflict_gdf)
    whatif_output_html = os.path.join(base_dir, 'makenes_whatif_safety_map.html')
    whatif_map_gen.generate_map(output_html=whatif_output_html, output_geojson=out_whatif, external_data=True)
    print("----------------------------------\n")

    print(f"Pipeline Complete. Standard Map: {output_html}")
    print(f"What-If Scenario Map: {whatif_output_html}")

if __name__ == "__main__":
    main()
