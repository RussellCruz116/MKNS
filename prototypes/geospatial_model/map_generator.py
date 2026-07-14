"""
map_generator.py (Visualization Engine)

Orchestrates the conversion of scored GeoPandas DataFrames and Agent-Based Model (ABM) 
kinematic logs into a high-performance, interactive MapLibre GL JS dashboard. 
Generates standalone HTML files fully decoupled from local python dependencies, 
ready for GitHub Pages or static web hosting.
"""

import os
import shutil
import geopandas as gpd
import json

class MapGenerator:
    """
    Generates a MapLibre GL interactive map.
    Exports the network to GeoJSON and creates an HTML shell for high-performance WebGL rendering.
    """
    def __init__(self, scored_network: gpd.GeoDataFrame, conflict_gdf: gpd.GeoDataFrame = None, frame_logs=None):
        self.network = scored_network
        self.conflict_gdf = conflict_gdf
        self.frame_logs = frame_logs or {}

    def generate_map(
        self,
        output_html="makenes_safety_map.html",
        output_geojson="makenes_scored.geojson",
        external_data=False,
        conflict_geojson_path=None,
    ):
        if self.network.empty:
            print("Network is empty. Cannot generate map.")
            return

        if self.network.crs != "EPSG:4326":
            self.network = self.network.to_crs("EPSG:4326")

        print("Serializing GeoJSON into memory (optimizing size)...")
        temp_net = self.network.copy()
        if temp_net.crs == "EPSG:4326":
            temp_net.geometry = temp_net.geometry.simplify(0.00005, preserve_topology=False)
            
        needed_cols = [
            'OBJECTID', 'SpeedSafetyScore', 'SafeSystemAligned', 'SubSupervisorID', 'InferredZone', 'LandUse',
            'SpeedLimit', 'F85thPercentileSpeed', 'OriginalSpeedLimit', 'Overture_Maxspeed',
            'Score_Kinematics', 'Score_Friction', 'Score_VRU', 'Score_Speeding', 'Score_AI', 'Score_Stress', 'Score_Infrastructure',
            'Max_Kinematics', 'Max_Friction', 'Max_VRU', 'Max_Speeding', 'Max_AI', 'Max_Stress', 'Max_Infrastructure',
            'ImputedFields', 'Intervention_Cost', 'Safety_ROI', 'AI_Score_Adjustment', 'AI_SpeedIntervention',
            'RankedPercentile', 'MedianSpeed', 'PercentOverLimit', 'SampleSize_avg',
            'SegmentConflicts_VRU', 'SegmentConflicts_V2V', 'SegmentConflicts_V2O', 'SegmentPETs', 'EffectiveHazards_VRU', 'ABM_Stress_Events',
            'Violated_Rules', 'WhatIf_Action_Details', 'PopDensity_100m', 'BuildingDensity_100m', 'UrbanCentre_Pop',
            'POI_Schools_500m', 'Mapillary_TrafficSigns', 'Mapillary_Crosswalks', 'OSM_Crossings_500m', 'OSM_StreetLighting_500m',
            'OSM_Cycleways_500m', 'OSM_Sidewalks_500m', 'OSM_TrafficCalming_500m', 'OSM_Barriers_500m', 'OSM_RoadSurface', 
            'OSM_LaneCount', 'OSM_MaxSpeed', 'OSM_LandUse', 'RoadClass', 'InfraGapPenalty', 'InfraBonus', 'SurfacePenalty', 
            'I_Infra_raw', 'I_Infra_norm', 'SpeedSafetyScore_PreShipRaw', 'geometry'
        ]
        existing_cols = [c for c in needed_cols if c in temp_net.columns]
        temp_net = temp_net[existing_cols]
        
        float_cols = temp_net.select_dtypes(include=['float64', 'float32']).columns
        for c in float_cols:
            temp_net[c] = temp_net[c].round(4)

        print("Exporting GeoJSON for MapLibre GL...")
        temp_net.to_file(output_geojson, driver="GeoJSON")

        geojson_basename = os.path.basename(output_geojson)
        if conflict_geojson_path is None:
            conflict_geojson_path = output_geojson.replace(".geojson", "_conflicts.geojson")
        conflict_basename = os.path.basename(conflict_geojson_path)

        output_dir = os.path.dirname(os.path.abspath(output_html)) or os.getcwd()
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        source_assets_dir = os.path.join(project_root, "assets")
        output_assets_dir = os.path.join(output_dir, "assets")
        local_assets = {
            "maplibre_js": "maplibre-gl.js",
            "maplibre_css": "maplibre-gl.css",
            "chart_js": "chart.umd.min.js",
        }
        use_local_assets = all(
            os.path.exists(os.path.join(source_assets_dir, filename))
            for filename in local_assets.values()
        )
        if use_local_assets:
            os.makedirs(output_assets_dir, exist_ok=True)
            for filename in local_assets.values():
                src = os.path.join(source_assets_dir, filename)
                dst = os.path.join(output_assets_dir, filename)
                if os.path.abspath(src) != os.path.abspath(dst):
                    shutil.copy2(src, dst)
            maplibre_js = "assets/maplibre-gl.js"
            maplibre_css = "assets/maplibre-gl.css"
            chart_js = "assets/chart.umd.min.js"
        else:
            maplibre_js = "https://cdn.jsdelivr.net/npm/maplibre-gl@4.5.0/dist/maplibre-gl.js"
            maplibre_css = "https://cdn.jsdelivr.net/npm/maplibre-gl@4.5.0/dist/maplibre-gl.css"
            chart_js = "https://cdn.jsdelivr.net/npm/chart.js"
        
        geojson_str = "null"
        if not external_data:
            geojson_str = temp_net.to_json(drop_id=True)
        
        conflict_geojson_str = '{"type": "FeatureCollection", "features": []}'
        if self.conflict_gdf is not None and not self.conflict_gdf.empty:
            if self.conflict_gdf.crs != "EPSG:4326":
                self.conflict_gdf = self.conflict_gdf.to_crs("EPSG:4326")
            # Downsample VRU points to prevent OOM/crashing the browser, keep all V2V, V2O, and PET points
            vru_gdf = self.conflict_gdf[self.conflict_gdf['type'] == 'VRU'].head(40000)
            v2v_gdf = self.conflict_gdf[self.conflict_gdf['type'] == 'V2V']
            v2o_gdf = self.conflict_gdf[self.conflict_gdf['type'] == 'V2O']
            pet_gdf = self.conflict_gdf[self.conflict_gdf['type'] == 'PET']
            import pandas as pd
            downsampled = gpd.GeoDataFrame(pd.concat([vru_gdf, v2v_gdf, v2o_gdf, pet_gdf], ignore_index=True), geometry='geometry', crs="EPSG:4326")
            conflict_geojson_str = downsampled.to_json()
            if external_data:
                downsampled.to_file(conflict_geojson_path, driver="GeoJSON")

        import json
        frame_json_str = json.dumps(self.frame_logs)

        centroid = self.network.geometry.unary_union.centroid

        if external_data:
            json_scripts = ""
            data_init_js = f"""
        const EXTERNAL_DATA = true;
        const GEOJSON_URL = '{geojson_basename}';
        const CONFLICT_URL = '{conflict_basename}';
        let geojsonUrl = GEOJSON_URL;
        let conflictUrl = CONFLICT_URL;
        let geojsonData = null;
        let conflictData = null;
"""
        else:
            json_scripts = "__JSON_SCRIPTS_PLACEHOLDER__"
            data_init_js = """
        const EXTERNAL_DATA = false;
        let geojsonUrl = null;
        let conflictUrl = null;
        let geojsonData = null;
        let conflictData = null;
"""
        
        map_load_prefix = """
        async function loadDashboardData() {
            const statusEl = document.getElementById('map-status');
            if (EXTERNAL_DATA) {
                const ts = new Date().getTime();
                geojsonUrl = GEOJSON_URL + '?v=' + ts;
                conflictUrl = CONFLICT_URL + '?v=' + ts;
                try {
                    if (statusEl) statusEl.textContent = 'Loading MaKeNeS road network...';
                    const [netResp, confResp] = await Promise.all([
                        fetch(geojsonUrl),
                        fetch(conflictUrl)
                    ]);
                    if (!netResp.ok) throw new Error(`Road network fetch failed: ${netResp.status} ${netResp.statusText}`);
                    if (!confResp.ok) throw new Error(`Conflict layer fetch failed: ${confResp.status} ${confResp.statusText}`);
                    geojsonData = await netResp.json();
                    conflictData = await confResp.json();
                    if (statusEl) statusEl.textContent = `Loaded ${geojsonData.features.length.toLocaleString()} segments`;
                } catch (err) {
                    console.error('MaKeNeS map data load failed', err);
                    if (statusEl) {
                        statusEl.textContent = 'Map data failed to load. Please check console for errors.';
                        statusEl.classList.add('error');
                    }
                    throw err;
                }
            } else {
                if (statusEl) statusEl.textContent = 'Parsing road network data...';
                await new Promise(r => setTimeout(r, 50)); // yield to render loading text
                
                const geojsonText = document.getElementById('geojson-data-src').textContent;
                const geojsonBlob = new Blob([geojsonText], { type: 'application/json' });
                geojsonUrl = URL.createObjectURL(geojsonBlob);
                geojsonData = JSON.parse(geojsonText);
                
                if (statusEl) statusEl.textContent = 'Parsing collision data...';
                await new Promise(r => setTimeout(r, 50));
                
                const conflictText = document.getElementById('conflict-data-src').textContent;
                const conflictBlob = new Blob([conflictText], { type: 'application/json' });
                conflictUrl = URL.createObjectURL(conflictBlob);
                conflictData = JSON.parse(conflictText);
                
                if (statusEl) statusEl.textContent = `Loaded ${geojsonData.features.length.toLocaleString()} segments`;
            }
        }
"""
        
        total_segments = len(self.network)
        mean_s3 = self.network['SpeedSafetyScore'].mean() if not self.network.empty else 0
        high_risk_count = len(self.network[self.network['SpeedSafetyScore'] <= 30])
        pct_high_risk = (high_risk_count / total_segments) * 100 if total_segments > 0 else 0
        
        num_sub_supervisors = self.network['SubSupervisorID'].nunique() if 'SubSupervisorID' in self.network.columns else 0

        # Compute global hazard counts explicitly
        total_v2v = 0
        total_v2o = 0
        total_vru = 0
        total_pet = 0
        if self.conflict_gdf is not None and not self.conflict_gdf.empty:
            total_v2v = len(self.conflict_gdf[self.conflict_gdf['type'] == 'V2V'])
            total_v2o = len(self.conflict_gdf[self.conflict_gdf['type'] == 'V2O'])
            total_vru = len(self.conflict_gdf[self.conflict_gdf['type'] == 'VRU'])
            total_pet = len(self.conflict_gdf[self.conflict_gdf['type'] == 'PET'])

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>MKNS Top 100 Safety Dashboard</title>
    <meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no">
    <script src="{maplibre_js}"></script>
    <script src="{chart_js}"></script>
    <link href="{maplibre_css}" rel="stylesheet" />
    <style>
        /* ============================================================
           DESIGN TOKENS — Phase 53a / 54c
           Single source of truth for all visual properties.
           ============================================================ */
        :root {{
            /* ---- Background Palette (dark slate to deep navy) ---- */
            --bg-body: #080e14;
            --bg-sidebar-start: #0c1620;
            --bg-sidebar-end: #111e2a;
            --bg-glass: rgba(14, 26, 38, 0.80);
            --bg-glass-hover: rgba(22, 38, 52, 0.90);
            --bg-glass-subtle: rgba(255, 255, 255, 0.025);
            --bg-overlay: rgba(10, 20, 30, 0.92);

            /* ---- Accent Colors ---- */
            --accent-cyan: #00e5ff;
            --accent-cyan-dim: rgba(0, 229, 255, 0.18);
            --accent-cyan-glow: rgba(0, 229, 255, 0.25);
            --accent-orange: #ff9800;
            --accent-orange-dim: rgba(255, 152, 0, 0.15);
            --accent-orange-glow: rgba(255, 152, 0, 0.35);
            --accent-teal-start: #00acc1;
            --accent-teal-end: #00838f;
            --accent-red: #ff5252;
            --accent-green: #66bb6a;
            --accent-purple: #e040fb;
            --accent-amber: #ffab40;
            --accent-blue: #40c4ff;

            /* ---- Risk Tier Colors ---- */
            --tier-critical: #ff3d3d;
            --tier-critical-glow: rgba(255, 61, 61, 0.25);
            --tier-high: #ff8a00;
            --tier-high-glow: rgba(255, 138, 0, 0.22);
            --tier-moderate: #f5c518;
            --tier-moderate-glow: rgba(245, 197, 24, 0.18);
            --tier-safe: #00c896;
            --tier-safe-glow: rgba(0, 200, 150, 0.15);

            /* ---- Text Colors ---- */
            --text-primary: #eceff1;
            --text-secondary: #b0bec5;
            --text-muted: #78909c;
            --text-heading: var(--accent-orange);

            /* ---- Borders & Dividers ---- */
            --border-subtle: rgba(255, 255, 255, 0.06);
            --border-medium: rgba(255, 255, 255, 0.10);
            --border-hover: rgba(0, 229, 255, 0.4);
            --divider: rgba(255, 255, 255, 0.08);

            /* ---- Spacing ---- */
            --sp-xs: 4px;
            --sp-sm: 8px;
            --sp-md: 14px;
            --sp-lg: 20px;
            --sp-xl: 28px;

            /* ---- Radii ---- */
            --radius-sm: 8px;
            --radius-md: 14px;
            --radius-lg: 20px;
            --radius-pill: 30px;

            /* ---- Shadows — Phase 54f layered depth ---- */
            --shadow-card: 0 4px 16px rgba(0,0,0,0.30), 0 16px 48px rgba(0,0,0,0.20);
            --shadow-hover: 0 8px 24px rgba(0,0,0,0.40), 0 20px 60px rgba(0,0,0,0.25);
            --shadow-overlay: 0 12px 60px rgba(0,0,0,0.65), 0 4px 12px rgba(0,0,0,0.4);
            --shadow-glow-cyan: 0 0 14px var(--accent-cyan-dim), 0 0 40px rgba(0,229,255,0.05);
            --shadow-glow-orange: 0 0 14px var(--accent-orange-dim), 0 0 40px rgba(255,152,0,0.05);
            --shadow-sidebar: 4px 0 40px rgba(0,0,0,0.5), 2px 0 8px rgba(0,0,0,0.3);

            /* ---- Typography ---- */
            --font-display: 'Outfit', system-ui, -apple-system, sans-serif;
            --font-body: 'Inter', 'Segoe UI', system-ui, sans-serif;
            --leading-tight: 1.25;
            --leading-normal: 1.55;
            --leading-relaxed: 1.7;
            --tracking-wide: 1.5px;
            --tracking-tight: -0.5px;

            /* ---- Transitions ---- */
            --ease-out: cubic-bezier(0.4, 0, 0.2, 1);
            --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
            --duration-fast: 0.18s;
            --duration-normal: 0.3s;
        }}

        /* ============================================================
           BASE RESET & TYPOGRAPHY
           ============================================================ */
        *, *::before, *::after {{ box-sizing: border-box; }}

        body {{ 
            margin: 0; padding: 0; 
            font-family: var(--font-body); 
            font-size: 13px;
            line-height: var(--leading-normal);
            color: var(--text-primary);
            background-color: var(--bg-body);
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}

        h2, h3, h4, .tab-btn, .metric-value, .top100-title, .top100-score {{
            font-family: var(--font-display);
        }}        
        /* ============================================================
           LAYOUT — Sidebar + Map
           ============================================================ */
        #map {{ position: absolute; top: 0; bottom: 0; right: 0; width: 75%; }}
        
        /* Phase 53g: Dark Popup Tooltips */
        .maplibregl-popup {{
            max-width: 320px !important;
            width: 320px !important;
        }}
        .maplibregl-popup-content {{
            background-color: var(--bg-surface) !important;
            color: var(--text-primary) !important;
            border-radius: var(--radius-md) !important;
            box-shadow: var(--shadow-overlay) !important;
            border: 1px solid var(--border-medium) !important;
            padding: 0 !important;
            overflow: hidden;
            font-family: var(--font-body) !important;
        }}
        .maplibregl-popup-tip {{
            border-top-color: var(--bg-surface) !important;
            border-bottom-color: var(--bg-surface) !important;
        }}
        .maplibregl-popup-close-button {{
            color: var(--text-secondary);
            font-size: 16px;
            padding: 4px 8px;
            transition: color var(--duration-fast);
        }}
        .maplibregl-popup-close-button:hover {{
            color: var(--text-primary);
            background-color: transparent !important;
        }}

        #sidebar {{
            position: absolute; top: 0; bottom: 0; left: 0; width: 25%;
            background: linear-gradient(175deg, var(--bg-sidebar-start) 0%, var(--bg-sidebar-end) 100%); 
            color: var(--text-primary); 
            padding: var(--sp-xl) var(--sp-lg);
            overflow-y: auto; 
            border-right: 1px solid var(--border-subtle);
            box-shadow: var(--shadow-sidebar);
        }}

        /* ============================================================
           GLASSMORPHIC CARDS
           ============================================================ */
        .metric-box {{
            background: var(--bg-glass); 
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border-radius: var(--radius-md); 
            padding: var(--sp-lg); 
            margin-bottom: var(--sp-lg);
            text-align: center; 
            border: 1px solid var(--border-subtle);
            box-shadow: var(--shadow-card);
            transition: transform var(--duration-fast) var(--ease-out), 
                        border-color var(--duration-normal) ease,
                        box-shadow var(--duration-normal) ease;
        }}
        .metric-box:hover {{
            transform: translateY(-3px);
            border-color: var(--accent-orange-glow);
            box-shadow: var(--shadow-hover);
        }}

        .metric-value {{ 
            font-size: 32px; font-weight: 700; 
            color: var(--accent-cyan);
            text-shadow: 0 0 14px var(--accent-cyan-dim);
            letter-spacing: var(--tracking-tight);
            line-height: var(--leading-tight);
        }}
        .metric-value.danger {{ 
            color: var(--accent-orange);
            text-shadow: 0 0 14px var(--accent-orange-dim);
        }}

        .metric-label {{ 
            font-family: var(--font-body);
            font-size: 10px; 
            color: var(--text-muted); 
            text-transform: uppercase; 
            letter-spacing: var(--tracking-wide); 
            margin-top: var(--sp-sm); 
            font-weight: 600;
        }}

        .scoring-desc {{ 
            font-size: 12px; color: var(--text-secondary); 
            margin-top: var(--sp-lg); 
            line-height: var(--leading-relaxed); 
            background: var(--bg-glass-subtle); 
            padding: var(--sp-md); 
            border-radius: var(--radius-sm); 
            border: 1px solid var(--border-subtle); 
        }}

        /* ============================================================
           MAP OVERLAY / LEGEND
           ============================================================ */
        .map-overlay {{
            position: absolute; bottom: 30px; right: 30px;
            background: var(--bg-overlay); 
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            color: var(--text-primary); 
            padding: var(--sp-lg); 
            border-radius: var(--radius-lg);
            width: 260px; 
            box-shadow: var(--shadow-overlay);
            border: 1px solid var(--border-subtle); 
            z-index: 1000;
            cursor: grab;
        }}
        .map-overlay:active {{ cursor: grabbing; }}
        .legend {{ display:block; }}

        /* ============================================================
           HEADINGS
           ============================================================ */
        h2 {{ 
            margin-top: 0; 
            color: var(--text-heading);
            font-size: 26px; font-weight: 700;
            margin-bottom: var(--sp-xs); 
            letter-spacing: var(--tracking-tight);
            line-height: var(--leading-tight);
        }}

        h3 {{ 
            font-size: 15px; 
            color: var(--text-primary); 
            font-weight: 600;
            margin-bottom: var(--sp-sm);
        }}

        h4 {{ 
            font-size: 13px; 
            font-weight: 600;
        }}

        /* ============================================================
           LEGEND ITEMS
           ============================================================ */
        .legend-item {{ display: flex; align-items: center; margin-bottom: var(--sp-sm); font-size: 12px; }}
        .legend-line {{ display: inline-block; width: 22px; height: 4px; margin-right: 10px; border-radius: 2px; }}
        .legend-scale {{ display: flex; height: 12px; width: 100%; margin-bottom: var(--sp-sm); border-radius: var(--radius-sm); overflow: hidden; }}
        .legend-scale span {{ flex: 1; height: 100%; }}
        .legend-labels {{ display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); margin-bottom: var(--sp-sm); }}
        
        /* ============================================================
           CURVED TAB SYSTEM WITH ANIMATED UNDERLINE (Phase 53i)
           ============================================================ */
        .tab-container {{ 
            display: flex; margin-bottom: var(--sp-lg); 
            background: transparent; 
            padding: 0; border-radius: 0;
            border-bottom: 2px solid var(--border-subtle);
        }}
        .tab-btn {{ 
            flex: 1; background: transparent; 
            color: var(--text-secondary); 
            border: none; padding: 12px var(--sp-sm); 
            cursor: pointer; font-size: 13px; font-weight: 600; 
            transition: color var(--duration-normal) var(--ease-out);
            font-family: var(--font-display);
            letter-spacing: 0.3px;
            position: relative;
            display: flex; align-items: center; justify-content: center; gap: 8px;
        }}
        .tab-btn::after {{
            content: ''; position: absolute; bottom: -2px; left: 0; width: 100%; height: 2px;
            background: var(--accent-cyan);
            transform: scaleX(0);
            transition: transform var(--duration-normal) var(--ease-out);
            transform-origin: center;
        }}
        .tab-btn svg {{ width: 16px; height: 16px; fill: currentColor; transition: transform var(--duration-fast); }}
        .tab-btn:hover {{ color: var(--text-primary); }}
        .tab-btn:hover svg {{ transform: translateY(-2px); }}
        .tab-btn.active {{ 
            color: var(--accent-cyan); 
            background: transparent;
            box-shadow: none;
        }}
        .tab-btn.active::after {{ transform: scaleX(1); }}
        .tab-content {{ 
            display: none; 
            animation: fadeSlideIn 0.4s var(--ease-out);
        }}
        .tab-content.active {{ display: block; }}
        
        @keyframes fadeSlideIn {{
            from {{ opacity: 0; transform: translateY(6px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        
        /* ============================================================
           TOP 100 & VIDEO LISTS
           ============================================================ */
        #top100-list, #video-list {{ max-height: 480px; overflow-y: auto; padding-right: var(--sp-sm); }}
        .top100-item {{ 
            background: var(--bg-glass-subtle); 
            border-radius: var(--radius-md); 
            padding: var(--sp-md); 
            margin-bottom: var(--sp-md);
            cursor: pointer; 
            border: 1px solid var(--border-subtle); 
            transition: all var(--duration-fast) var(--ease-out);
        }}
        .top100-item:hover {{ 
            background: var(--bg-glass-hover); 
            border-color: var(--accent-cyan); 
            transform: translateY(-2px);
            box-shadow: 0 6px 24px var(--accent-cyan-dim);
        }}
        .top100-title {{ font-weight: 600; font-size: 14px; color: var(--accent-orange); margin-bottom: 6px; }}
        .top100-score {{ font-size: 18px; font-weight: 700; color: var(--accent-cyan); float: right; }}
        .top100-desc {{ font-size: 12px; color: var(--text-secondary); margin-bottom: var(--sp-xs); font-family: var(--font-body); }}
        
        /* ============================================================
           SCROLLBAR
           ============================================================ */
        ::-webkit-scrollbar {{ width: 5px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: rgba(255, 255, 255, 0.08); border-radius: 10px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: rgba(255, 255, 255, 0.18); }}

        /* ============================================================
           MAPLIBRE POPUP DARK THEME OVERRIDE
           ============================================================ */
        .maplibregl-popup {{
            max-width: 320px !important;
            width: 320px !important;
        }}
        .maplibregl-popup-content {{
            background: #111d28 !important;
            color: #eceff1 !important;
            border-radius: 14px !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            box-shadow: 0 12px 48px rgba(0, 0, 0, 0.65) !important;
            padding: 0 !important;
            font-family: 'Inter', 'Segoe UI', sans-serif !important;
        }}
        .maplibregl-popup-tip {{
            border-top-color: #111d28 !important;
            border-bottom-color: #111d28 !important;
        }}
        .maplibregl-popup-close-button {{
            color: #78909c !important;
            font-size: 18px !important;
            padding: 4px 8px !important;
            right: 4px !important;
            top: 4px !important;
        }}
        .maplibregl-popup-close-button:hover {{
            color: #ff9800 !important;
            background: transparent !important;
        }}

        /* ============================================================
           POPUP ACCORDIONS — Phase 53h
           ============================================================ */
        .popup-header-toggle {{
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 10px;
            font-weight: 600;
            font-size: 10px;
            color: var(--text-secondary);
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            margin-top: 8px;
            user-select: none;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            transition: all var(--duration-fast) var(--ease-out);
        }}
        .popup-header-toggle:hover {{
            color: var(--accent-cyan);
            border-color: rgba(0, 229, 255, 0.2);
            background: rgba(0, 229, 255, 0.02);
        }}
        /* ============================================================
           SMOOTH ACCORDION — Phase 54d
           Uses max-height transitions instead of display toggling.
           ============================================================ */
        .popup-section-content {{
            overflow: hidden;
            max-height: 0;
            transition: max-height 0.35s cubic-bezier(0.4, 0, 0.2, 1), padding 0.2s ease;
        }}
        .popup-section-content.expanded {{
            max-height: 600px;
        }}

        /* ============================================================
           RISK TIER BORDERS — Phase 54g
           Color-coded left borders for Top 100 items.
           ============================================================ */
        .top100-item.tier-critical {{ border-left: 3px solid var(--tier-critical); }}
        .top100-item.tier-high {{ border-left: 3px solid var(--tier-high); }}
        .top100-item.tier-moderate {{ border-left: 3px solid var(--tier-moderate); }}
        .top100-item.tier-safe {{ border-left: 3px solid var(--tier-safe); }}
        .top100-item.tier-critical:hover {{ box-shadow: 0 6px 24px var(--tier-critical-glow); }}
        .top100-item.tier-high:hover {{ box-shadow: 0 6px 24px var(--tier-high-glow); }}
        .top100-item.tier-moderate:hover {{ box-shadow: 0 6px 24px var(--tier-moderate-glow); }}
        .top100-item.tier-safe:hover {{ box-shadow: 0 6px 24px var(--tier-safe-glow); }}

        /* ============================================================
           FLOATING LAYER PANEL — Phase 54h
           ============================================================ */
        #layer-panel {{
            position: absolute;
            top: 20px;
            right: 20px;
            z-index: 1001;
            background: var(--bg-overlay);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            border: 1px solid var(--border-medium);
            border-radius: var(--radius-md);
            padding: 14px 16px;
            width: 200px;
            box-shadow: var(--shadow-overlay);
        }}
        #layer-panel .panel-title {{
            font-size: 9px;
            font-family: var(--font-body);
            text-transform: uppercase;
            letter-spacing: 1.2px;
            color: var(--text-muted);
            margin-bottom: 10px;
            font-weight: 600;
        }}
        #layer-panel label {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: var(--text-secondary);
            cursor: pointer;
            padding: 6px 8px;
            border-radius: 6px;
            transition: background var(--duration-fast) var(--ease-out);
            margin-bottom: 2px;
        }}
        #layer-panel label:hover {{
            background: var(--bg-glass-subtle);
            color: var(--text-primary);
        }}

        /* ============================================================
           MICRO-INTERACTIONS — Phase 54i
           Active tab underline + button transforms.
           ============================================================ */
        .tab-btn {{
            position: relative;
        }}
        .tab-btn.active::after {{
            content: '';
            position: absolute;
            bottom: 3px;
            left: 50%;
            transform: translateX(-50%);
            width: 18px;
            height: 2px;
            background: rgba(255,255,255,0.8);
            border-radius: 2px;
        }}
        .cta-btn {{
            transition: transform var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out) !important;
        }}
        .cta-btn:hover {{
            transform: translateY(-2px) !important;
            box-shadow: 0 8px 25px rgba(255, 152, 0, 0.45) !important;
        }}
        .cta-btn:active {{
            transform: translateY(0px) !important;
        }}
        #map-status {{
            position:absolute;
            top:12px;
            left:calc(25% + 14px);
            z-index:3;
            padding:8px 12px;
            background:rgba(7,16,23,0.88);
            color:var(--text-secondary);
            border:1px solid var(--border-subtle);
            border-radius:6px;
            font-size:11px;
            box-shadow:var(--shadow-card);
            pointer-events:none;
        }}
        #map-status.error {{
            color:var(--accent-red);
            border-color:rgba(255,82,82,0.5);
            max-width:360px;
        }}

        /* ============================================================
           RESPONSIVE DESIGN — Phase 53j
           ============================================================ */
        @media (max-width: 1024px) {{
            #sidebar {{ width: 30%; }}
            #map {{ width: 70%; }}
        }}

        @media (max-width: 768px) {{
            #sidebar {{
                width: 100%;
                height: 45%;
                top: auto;
                bottom: 0;
                border-right: none;
                border-top: 1px solid var(--border-subtle);
                padding: var(--sp-md) var(--sp-lg);
            }}
            #map {{
                width: 100%;
                height: 55%;
                bottom: auto;
                top: 0;
            }}
            .map-overlay {{
                bottom: calc(45% + 15px) !important;
                right: 15px !important;
                width: calc(100% - 30px) !important;
                max-width: 320px !important;
                padding: var(--sp-md) !important;
            }}
            #top100-list, #video-list {{
                max-height: 200px;
            }}
        }}
        /* ============================================================
           PHASE 53j: RESPONSIVE DESIGN (@media)
           ============================================================ */
        @media (max-width: 900px) {{
            #sidebar {{ width: 35%; }}
            #map {{ width: 65%; }}
        }}
        @media (max-width: 600px) {{
            #sidebar {{
                position: absolute;
                top: 60%; bottom: 0; left: 0; width: 100%;
                z-index: 1000;
                border-right: none;
                border-top: 2px solid var(--accent-cyan);
            }}
            #map {{
                position: absolute;
                top: 0; bottom: 40%; right: 0; width: 100%;
            }}
            .legend-panel {{
                bottom: auto; top: 10px; right: 10px; left: 10px; max-width: none;
            }}
            .layer-panel {{
                top: auto; bottom: 42%; right: 10px;
            }}
        }}
    </style>
</head>
<body>
    <!-- Phase 54h: Floating Layer Control Panel -->
    <div id="layer-panel">
        <div class="panel-title">Map Layers</div>
        <label style="font-weight:600; color:var(--accent-cyan);">
            <input type="radio" id="layer-s3" name="map-layer" value="s3" checked style="accent-color:var(--accent-cyan);">
            S&#179; Safety Score
        </label>
        <label>
            <input type="radio" id="layer-safe" name="map-layer" value="safe" style="accent-color:var(--accent-cyan);">
            Safe System Violations
        </label>
        <div style="margin-top:8px; padding-top:8px; border-top:1px solid var(--border-subtle);">
            <label style="color:var(--accent-amber); font-weight:600;">
                <input type="checkbox" id="layer-abm" checked style="accent-color:var(--accent-amber);">
                ABM Collision Overlay
            </label>
        </div>
        <div style="margin-top:4px; padding-top:4px;">
            <label style="color:var(--accent-cyan); font-weight:600;">
                <input type="checkbox" id="layer-infra-pins" checked style="accent-color:var(--accent-cyan);">
                Infrastructure Pins
            </label>
        </div>
    </div>

    <div id="sidebar">
        <!-- Phase 54c: Asymmetric Header — brand + status bar -->
        <div style="display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:var(--sp-md);">
            <div>
                <h2 style="margin-bottom:2px;">MKNS</h2>
                <p style="font-size:10px; color:var(--text-muted); margin:0; text-transform:uppercase; letter-spacing:1.2px; font-weight:600;">Digital Twin Analytics</p>
            </div>
            <div style="text-align:right;">
                <div style="width:8px; height:8px; border-radius:50%; background:var(--accent-green); display:inline-block; box-shadow:0 0 8px rgba(102,187,106,0.6); margin-right:4px;"></div>
                <span style="font-size:9px; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px;">Live</span>
            </div>
        </div>
        <p style="font-size:11px; color:var(--text-secondary); margin-bottom:var(--sp-lg); line-height:var(--leading-normal); border-left:2px solid var(--accent-cyan); padding-left:8px;">Mobility Agents and Kinematic Environment Network Simulator &mdash; <span style="color:var(--accent-cyan); font-weight:500;">AI-Supervised</span></p>
        
        <div class="tab-container">
            <button class="tab-btn active" onclick="switchTab('analytics')">
                <svg viewBox="0 0 24 24"><path d="M3 3h8v8H3zm10 0h8v8h-8zM3 13h8v8H3zm10 0h8v8h-8z"/></svg> Overview
            </button>
            <button class="tab-btn" onclick="switchTab('top100')">
                <svg viewBox="0 0 24 24"><path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/></svg> Top 100
            </button>
            <button class="tab-btn" onclick="window.location.href='makenes_whatif_safety_map.html';">
                <svg viewBox="0 0 24 24"><path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.06-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41 h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.73,8.87 C2.62,9.08,2.66,9.34,2.86,9.48l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.06,0.94l-2.03,1.58 c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54 c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.43-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96 c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.49-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6 s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/></svg> What-If
            </button>
            <button class="tab-btn" onclick="switchTab('videos')">
                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg> ABM Replay
            </button>
        </div>
        
        <div id="analytics" class="tab-content active">
            <!-- Hero Stat: Mean MKNS score - F-pattern top-left anchor -->
            <div class="metric-box" style="border-left: 3px solid var(--accent-cyan); text-align:left; padding-left:var(--sp-xl);">
                <div style="display:flex; align-items:baseline; gap:var(--sp-sm);">
                    <div class="metric-value">{mean_s3:.1f}</div>
                    <span style="font-size:14px; color:var(--text-muted); font-weight:400;">/ 100</span>
                </div>
                <div class="metric-label">MKNS Safety Score (Mean)</div>
            </div>

            <!-- Two-column metric row -->
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:var(--sp-md); margin-bottom:var(--sp-lg);">
                <div class="metric-box" style="margin-bottom:0;">
                    <div class="metric-value" style="font-size:24px;">{total_segments:,}</div>
                    <div class="metric-label">Segments</div>
                </div>
                <div class="metric-box" style="margin-bottom:0; border-left:3px solid var(--accent-orange);">
                    <div class="metric-value danger" style="font-size:24px;">{high_risk_count:,}</div>
                    <div class="metric-label">Priority Review ({pct_high_risk:.1f}%)</div>
                </div>
            </div>

            <!-- Score Distribution Chart — glassmorphic container -->
            <div style="padding:var(--sp-md); background:var(--bg-glass); border:1px solid var(--border-subtle); border-radius:var(--radius-md); margin-bottom:var(--sp-lg); box-shadow:var(--shadow-card);">
                <canvas id="scoreChart" height="110"></canvas>
            </div>
            
            <div class="scoring-desc">
                <b style="color:var(--text-primary);">MKNS Score:</b> A 7-part safety score combining speed physics, contextual friction, vulnerable-road-user exposure, speeding, AI review, active ABM stress, and infrastructure gaps. Lower scores mark segments for earlier review.
            </div>
            
            <hr style="border:0; border-top:1px solid var(--divider); margin:var(--sp-lg) 0;">
            
            <!-- AI Swarm Status — compact card -->
            <div style="background:var(--bg-glass-subtle); border-radius:var(--radius-sm); padding:var(--sp-md); border:1px solid var(--border-subtle); margin-bottom:var(--sp-lg);">
                <h3 style="font-size:13px; margin-top:0; margin-bottom:var(--sp-sm);">AI Swarm Status</h3>
                <div style="font-size:11px; color:var(--text-secondary); line-height:var(--leading-relaxed);">
                    <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                        <span style="width:6px; height:6px; border-radius:50%; background:var(--accent-green); display:inline-block;"></span>
                        Hierarchical Topology Active
                    </div>
                    <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                        <span style="width:6px; height:6px; border-radius:50%; background:var(--accent-cyan); display:inline-block;"></span>
                        {num_sub_supervisors} Sub-Supervisors Spawned
                    </div>
                    <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                        <span style="width:6px; height:6px; border-radius:50%; background:var(--accent-purple); display:inline-block;"></span>
                        K-Means Density Clustering Applied
                    </div>
                </div>
            </div>
            
            <!-- Global ABM Hazard Log — styled with colored dots -->
            <div style="background:var(--bg-glass-subtle); border-radius:var(--radius-sm); padding:var(--sp-md); border:1px solid var(--border-subtle); margin-bottom:var(--sp-lg);">
                <h3 style="font-size:13px; margin-top:0; margin-bottom:var(--sp-sm);">ABM Hazard Summary</h3>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:var(--sp-sm);">
                    <div style="font-size:11px; color:var(--text-secondary); display:flex; align-items:center; gap:6px;">
                        <span style="width:8px; height:8px; border-radius:50%; background:var(--accent-red); display:inline-block;"></span>
                        V2V: <b style="color:var(--accent-red);">{total_v2v}</b>
                    </div>
                    <div style="font-size:11px; color:var(--text-secondary); display:flex; align-items:center; gap:6px;">
                        <span style="width:8px; height:8px; border-radius:50%; background:var(--accent-blue); display:inline-block;"></span>
                        V2O: <b style="color:var(--accent-blue);">{total_v2o}</b>
                    </div>
                    <div style="font-size:11px; color:var(--text-secondary); display:flex; align-items:center; gap:6px;">
                        <span style="width:8px; height:8px; border-radius:50%; background:var(--accent-purple); display:inline-block;"></span>
                        VRU: <b style="color:var(--accent-purple);">{total_vru}</b>
                    </div>
                    <div style="font-size:11px; color:var(--text-secondary); display:flex; align-items:center; gap:6px;">
                        <span style="width:8px; height:8px; border-radius:50%; background:var(--accent-amber); display:inline-block;"></span>
                        PET: <b style="color:var(--accent-amber);">{total_pet}</b>
                    </div>
                </div>
            </div>
            
            <hr style="border:0; border-top:1px solid var(--divider); margin:var(--sp-lg) 0;">
            
            <!-- Visualization Layer Toggles -->
            <!-- Phase 54j: Executive Summary Card -->
            <div style="background:linear-gradient(135deg, rgba(0,172,193,0.08), rgba(0,100,130,0.04)); border:1px solid rgba(0,229,255,0.12); border-radius:var(--radius-md); padding:var(--sp-md); margin-bottom:var(--sp-lg); box-shadow: var(--shadow-card);">
                <div style="font-size:9px; text-transform:uppercase; letter-spacing:1.2px; color:var(--accent-cyan); font-weight:700; margin-bottom:8px;">Network Intelligence Summary</div>
                <div style="font-size:11px; color:var(--text-secondary); line-height:var(--leading-relaxed);">
                    <span style="color:var(--tier-critical); font-weight:700;">{pct_high_risk:.0f}%</span> of segments are flagged for priority review.
                    The network carries <span style="color:var(--accent-amber); font-weight:600;">{total_v2v:,} V2V</span> and
                    <span style="color:var(--accent-purple); font-weight:600;">{total_vru:,} VRU</span> simulated conflict events.
                    Mean kinematic score across <span style="color:var(--accent-cyan); font-weight:600;">{total_segments:,} segments</span>
                    is <span style="color:var(--accent-orange); font-weight:700;">{mean_s3:.1f}/100</span>.
                </div>
            </div>

            <!-- CTA: Export Report Button — Phase 54i micro-interaction -->
            <div style="margin-top:var(--sp-md); margin-bottom:var(--sp-md); text-align:center;">
                <a href="https://github.com/makenes" target="_blank" class="cta-btn" style="display:inline-block; width:100%; padding:13px var(--sp-md); background:linear-gradient(135deg, var(--accent-orange), #e65100); color:#fff; text-decoration:none; border-radius:var(--radius-md); font-weight:700; font-family:var(--font-display); font-size:12px; letter-spacing:0.8px; box-shadow:0 4px 20px rgba(255,152,0,0.35); text-align:center; text-transform:uppercase;">
                    Export Safety Report
                </a>
            </div>
        </div>
        
        <div id="top100" class="tab-content">
            <h2 style="margin-bottom:2px;">MKNS</h2>
                <div style="font-size: 10px; color: #00e676; font-weight: bold; margin-bottom: 12px; border: 1px solid #00e676; padding: 4px 6px; border-radius: 4px; display: inline-block; background: rgba(0, 230, 118, 0.1);">
                    ✓ AI Agent Supervisor/Evaluator Synergy: ALL Intervention Requests Accepted
                </div>
                <div style="font-size:12px; color:var(--text-secondary); margin-bottom:15px; font-weight:500;">Safety Analysis Dashboard</div>
            <div style="font-size:12px; color:var(--text-secondary); margin-bottom:var(--sp-md); line-height:var(--leading-normal);">
                The <b style="color:var(--accent-orange);">100 highest-priority segments</b> in the network. ABM hazard multipliers and kinematic speed deltas identify where speed review and countermeasure design should start.
            </div>
            <div id="top100-list"></div>
        </div>

        <div id="videos" class="tab-content">
            <div style="font-size:12px; color:var(--text-secondary); margin-bottom:var(--sp-md); line-height:var(--leading-normal);">
                Segments with full <b style="color:var(--accent-cyan);">Agent-Based Model (ABM) physics replay</b>. Click Play to watch simulated vehicle-VRU conflicts unfold.
            </div>
            <div id="video-list"></div>
        </div>
    </div>
    
    <div id="map"></div>
    <div id="map-status">Initializing MKNS map...</div>
    
    <div class="map-overlay" id="legend">
        <!-- Drag grip handle for discoverability -->
        <div style="text-align:center; margin-bottom:var(--sp-sm); cursor:grab;">
            <span style="color:var(--text-muted); font-size:14px; letter-spacing:3px;">⋮⋮</span>
        </div>
        <!-- S3 Legend -->
        <div id="legend-s3" style="display:block;">
            <h4 style="margin-top:0; color:var(--accent-amber); font-size:12px; letter-spacing:0.5px;">MKNS Safety Score</h4>
            <div class="legend-scale">
                <span style="background:#d73027"></span>
                <span style="background:#f46d43"></span>
                <span style="background:#fdae61"></span>
                <span style="background:#fee08b"></span>
                <span style="background:#ffd54f"></span>
                <span style="background:#e6f598"></span>
                <span style="background:#d9ef8b"></span>
                <span style="background:#a6d96a"></span>
                <span style="background:#66bd63"></span>
                <span style="background:#006837"></span>
            </div>
            <div class="legend-labels">
                <span>0 (Highest priority)</span>
                <span>100 (Lower concern)</span>
            </div>
        </div>
        
        <!-- Safe System Legend -->
        <div id="legend-safe" style="display:none;">
            <h4 style="margin-top:0; color:var(--accent-amber); font-size:12px;">Safe System Alignment</h4>
            <div class="legend-item">
                <span class="legend-line" style="background-color:var(--accent-green);"></span>
                <span style="font-size:11px;">Aligned</span>
            </div>
            <div class="legend-item">
                <span class="legend-line" style="background-color:var(--accent-red);"></span>
                <span style="font-size:11px;">Review flag</span>
            </div>
        </div>
        
        <hr style="border:0; border-top:1px solid var(--divider); margin:var(--sp-sm) 0;">
        <h4 style="color:var(--accent-amber); margin-top:0; font-size:12px;">ABM Hazards</h4>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
            <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
                <span style="width:10px; height:10px; border-radius:50%; background:var(--accent-purple); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>VRU
            </div>
            <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
                <span style="width:10px; height:10px; border-radius:2px; background:var(--accent-red); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>V2V
            </div>
            <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
                <span style="width:10px; height:10px; border-radius:2px; background:var(--accent-blue); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>V2O
            </div>
            <div style="font-size:11px; display:flex; align-items:center; gap:6px;">
                <span style="width:10px; height:10px; border-radius:50%; background:var(--accent-amber); border:1.5px solid rgba(255,255,255,0.6); display:inline-block;"></span>PET
            </div>
        </div>
    </div>

    {json_scripts}
    <script>
        {data_init_js}
        const frameData = {frame_json_str};
        
        function playSimulation(segmentId) {{
            const data = frameData[segmentId];
            if (!data || !data.frames || data.frames.length === 0) return;
            const frames = data.frames;
            const shape = data.shape || [];
            
            // Create or get modal
            let modal = document.getElementById('abmModal');
            if (!modal) {{
                modal = document.createElement('div');
                modal.id = 'abmModal';
                modal.style.position = 'fixed';
                modal.style.top = '0'; modal.style.left = '0';
                modal.style.width = '100%'; modal.style.height = '100%';
                modal.style.backgroundColor = 'rgba(0,0,0,0.9)';
                modal.style.zIndex = '9999';
                modal.style.display = 'flex';
                modal.style.flexDirection = 'column';
                modal.style.justifyContent = 'center';
                modal.style.alignItems = 'center';
                
                const closeBtn = document.createElement('button');
                closeBtn.innerText = 'Close';
                closeBtn.style.position = 'absolute';
                closeBtn.style.top = '20px'; closeBtn.style.right = '20px';
                closeBtn.style.padding = '10px 20px'; closeBtn.style.fontSize = '16px';
                closeBtn.style.cursor = 'pointer'; closeBtn.style.background = '#444';
                closeBtn.style.color = '#fff'; closeBtn.style.border = 'none'; closeBtn.style.borderRadius = '5px';
                closeBtn.onclick = () => {{
                    modal.style.display = 'none';
                    window.cancelAnimationFrame(modal.animId);
                    if (window.miniMapInstance) {{
                        window.miniMapInstance.remove();
                        window.miniMapInstance = null;
                    }}
                }};
                modal.appendChild(closeBtn);
                
                const title = document.createElement('h2');
                title.id = 'abmModalTitle';
                title.style.color = '#FFD54F';
                title.style.marginBottom = '10px';
                modal.appendChild(title);

                const frameCounter = document.createElement('div');
                frameCounter.id = 'frameCounter';
                frameCounter.style.color = '#4FC3F7';
                frameCounter.style.fontSize = '18px';
                frameCounter.style.fontWeight = 'bold';
                frameCounter.style.marginBottom = '10px';
                modal.appendChild(frameCounter);
                
                const mapContainer = document.createElement('div');
                mapContainer.id = 'abmMap';
                mapContainer.style.position = 'relative';
                mapContainer.style.width = '800px'; mapContainer.style.height = '600px';
                mapContainer.style.border = '2px solid #555'; mapContainer.style.borderRadius = '8px';
                
                const videoLegend = document.createElement('div');
                videoLegend.id = 'videoLegend';
                videoLegend.style.position = 'absolute';
                videoLegend.style.bottom = '20px';
                videoLegend.style.left = '20px';
                videoLegend.style.background = 'rgba(20, 20, 20, 0.9)';
                videoLegend.style.color = '#fff';
                videoLegend.style.padding = '10px 15px';
                videoLegend.style.borderRadius = '6px';
                videoLegend.style.border = '1px solid #444';
                videoLegend.style.fontFamily = 'sans-serif';
                videoLegend.style.fontSize = '12px';
                videoLegend.style.zIndex = '10000';
                videoLegend.innerHTML = `
                    <h4 style="margin:0 0 8px 0; color:#FFD54F; font-size:13px;">Actor Legend</h4>
                    <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#e040fb; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Pedestrian</div>
                    <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#76ff03; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Cyclist</div>
                    <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#ffab40; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>PTW (Motorcycle)</div>
                    <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#40c4ff; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Car</div>
                    <div style="margin-bottom:4px;"><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#ff5252; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>HGV (Truck)</div>
                    <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#777; margin-right:6px; border:1px solid #fff; vertical-align:middle;"></span>Obstruction</div>
                `;
                mapContainer.appendChild(videoLegend);
                modal.appendChild(mapContainer);
                
                document.body.appendChild(modal);
            }}
            
            modal.style.display = 'flex';
            document.getElementById('abmModalTitle').innerText = 'Segment ID: ' + segmentId + ' - ABM Physics Replay';
            document.getElementById('frameCounter').innerText = 'Loading segment satellite map patch...';
            
            if (window.miniMapInstance) {{
                window.miniMapInstance.remove();
                window.miniMapInstance = null;
            }}
            
            const miniMap = new maplibregl.Map({{
                container: 'abmMap',
                style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
                center: shape[0] || [0,0],
                zoom: 17,
                interactive: true
            }});
            window.miniMapInstance = miniMap;
            
            const bounds = new maplibregl.LngLatBounds();
            shape.forEach(p => bounds.extend(p));
            miniMap.fitBounds(bounds, {{ padding: 80, animate: false }});
            
            miniMap.on('load', () => {{
                miniMap.addSource('segment-line', {{
                    type: 'geojson',
                    data: {{
                        type: 'Feature',
                        geometry: {{
                            type: 'LineString',
                            coordinates: shape
                        }}
                    }}
                }});
                
                miniMap.addLayer({{
                    id: 'segment-line-glow',
                    type: 'line',
                    source: 'segment-line',
                    paint: {{
                        'line-color': '#fff',
                        'line-width': 6,
                        'line-opacity': 0.4
                    }}
                }});

                miniMap.addSource('actors', {{
                    type: 'geojson',
                    data: {{ type: 'FeatureCollection', features: [] }}
                }});

                miniMap.addLayer({{
                    id: 'actor-points',
                    type: 'circle',
                    source: 'actors',
                    paint: {{
                        'circle-radius': [
                            'match',
                            ['get', 'type'],
                            'Pedestrian', 6,
                            'Cyclist', 7,
                            'Obstruction', 8,
                            /* vehicle */ 10
                        ],
                        'circle-color': [
                            'match',
                            ['get', 'type'],
                            'Pedestrian', '#e040fb',
                            'Cyclist', '#76ff03',
                            'PTW', '#ffab40',
                            'HGV', '#ff5252',
                            'Obstruction', '#777',
                            /* Car */ '#40c4ff'
                        ],
                        'circle-opacity': 0.85,
                        'circle-stroke-width': 1.5,
                        'circle-stroke-color': '#ffffff'
                    }}
                }});

                let currentFrame = 0;
                let lastTime = 0;
                function draw(time) {{
                    if (modal.style.display === 'none') return;
                    
                    if (time - lastTime > 60) {{ // ~15 frames per second
                        lastTime = time;
                        
                        if (currentFrame >= frames.length) {{
                            currentFrame = 0;
                        }}
                        
                        const actors = frames[currentFrame] || [];
                        const features = actors.map(a => ({{
                            type: 'Feature',
                            geometry: {{
                                type: 'Point',
                                coordinates: [a.x, a.y]
                            }},
                            properties: {{
                                id: a.id,
                                type: a.type
                            }}
                        }}));
                        
                        miniMap.getSource('actors').setData({{
                            type: 'FeatureCollection',
                            features: features
                        }});
                        
                        document.getElementById('frameCounter').innerText = 'Frame: ' + currentFrame + ' / ' + frames.length;
                        currentFrame++;
                    }}
                    modal.animId = window.requestAnimationFrame(draw);
                }}
                modal.animId = window.requestAnimationFrame(draw);
            }});
        }}
        
        // Generate Top 100 List
        function initTop100() {{
            const features = geojsonData.features.slice();
            // Sort by lowest S3 score
            features.sort((a, b) => (a.properties.SpeedSafetyScore || 100) - (b.properties.SpeedSafetyScore || 100));
            const top100 = features.slice(0, 100);
            
            const listEl = document.getElementById('top100-list');
            const videoEl = document.getElementById('video-list');
            listEl.innerHTML = '';
            videoEl.innerHTML = '';
            
            const getScoreColor = (score) => {{
                if (score < 20) return 'var(--accent-red)';
                if (score <= 30) return 'var(--accent-orange)';
                if (score < 60) return 'var(--accent-amber)';
                return 'var(--accent-green)';
            }};

            top100.forEach((feat, index) => {{
                const s3Val = feat.properties.SpeedSafetyScore || 0;
                const s3 = s3Val.toFixed(3);
                const limit = feat.properties.SpeedLimit || 50;
                const f85 = (feat.properties.F85thPercentileSpeed || 0).toFixed(1);
                const zone = feat.properties.InferredZone || 'Unknown Zone';
                
                // Get centroid for clicking
                let lngLat = null;
                if (feat.geometry.type === 'LineString' && feat.geometry.coordinates.length > 0) {{
                    const mid = Math.floor(feat.geometry.coordinates.length / 2);
                    lngLat = feat.geometry.coordinates[mid];
                }} else if (feat.geometry.type === 'Point') {{
                    lngLat = feat.geometry.coordinates;
                }}
                
                const hasVideo = frameData[feat.properties.OBJECTID] ? true : false;
                const videoBtn = hasVideo ? `<button onclick="event.stopPropagation(); playSimulation('${{feat.properties.OBJECTID}}')" style="margin-top:10px; width:100%; padding:8px; background:linear-gradient(135deg, #00acc1, #00838f); color:#fff; border:none; border-radius:6px; cursor:pointer; font-weight:600; font-size:12px; transition: background 0.2s; box-shadow:0 2px 8px rgba(0,172,193,0.25);">Play ABM Simulation</button>` : '';

                const violatedRules = feat.properties.Violated_Rules && feat.properties.Violated_Rules !== "None" ? `<div style="font-size:11px; color:var(--accent-red); margin-top:3px; font-weight:500;">&#9888; ${{feat.properties.Violated_Rules}}</div>` : '';
                const item = document.createElement('div');
                // Phase 54g: Risk tier class based on score
                let tierClass = 'tier-safe';
                if (s3Val <= 30) tierClass = 'tier-critical';
                else if (s3Val < 45) tierClass = 'tier-high';
                else if (s3Val < 65) tierClass = 'tier-moderate';
                item.className = 'top100-item ' + tierClass;
                
                // Highlight #1 worst segment
                if (index === 0) {{
                    item.style.border = '2px solid var(--tier-critical)';
                    item.style.boxShadow = '0 0 20px var(--tier-critical-glow)';
                    item.style.background = 'rgba(255,61,61,0.05)';
                }}

                item.innerHTML = `
                    <span class="top100-score" style="color:${{getScoreColor(s3Val)}};">${{s3}}</span>
                    <div class="top100-title">${{index === 0 ? 'HIGHEST PRIORITY' : 'Rank ' + (index + 1)}}: ${{zone}}</div>
                    <div class="top100-desc">Limit: ${{limit}} km/h | Flow: ${{f85}} km/h</div>
                    <div style="width: 100%; background: rgba(255,255,255,0.06); height: 4px; border-radius: 2px; margin-top: 8px; overflow: hidden;">
                        <div style="width: ${{s3Val}}%; background: ${{getScoreColor(s3Val)}}; height: 100%; border-radius: 2px;"></div>
                    </div>
                    ${{violatedRules}}
                    ${{videoBtn}}
                `;
                
                if (lngLat) {{
                    item.onclick = () => flyToSegment(lngLat, feat.properties);
                }}
                listEl.appendChild(item);
            }});

            // Guarantee Video Tab gets exactly the 50 segments that have frameData
            const videoFeatures = geojsonData.features.filter(f => frameData[f.properties.OBJECTID]);
            videoFeatures.forEach((feat, index) => {{
                const s3Val = feat.properties.SpeedSafetyScore || 0;
                const s3 = s3Val.toFixed(3);
                const limit = feat.properties.SpeedLimit || 50;
                const f85 = (feat.properties.F85thPercentileSpeed || 0).toFixed(1);
                const zone = feat.properties.InferredZone || 'Unknown Zone';
                
                let lngLat = null;
                if (feat.geometry.type === 'LineString' && feat.geometry.coordinates.length > 0) {{
                    const mid = Math.floor(feat.geometry.coordinates.length / 2);
                    lngLat = feat.geometry.coordinates[mid];
                }} else if (feat.geometry.type === 'Point') {{
                    lngLat = feat.geometry.coordinates;
                }}
                
                const videoBtn = `<button onclick="event.stopPropagation(); playSimulation('${{feat.properties.OBJECTID}}')" style="margin-top:10px; width:100%; padding:8px; background:linear-gradient(135deg, #00acc1, #00838f); color:#fff; border:none; border-radius:6px; cursor:pointer; font-weight:600; font-size:12px; transition: background 0.2s; box-shadow:0 2px 8px rgba(0,172,193,0.25);">Play ABM Simulation</button>`;

                const item = document.createElement('div');
                item.className = 'top100-item';
                item.innerHTML = `
                    <span class="top100-score" style="color:${{getScoreColor(s3Val)}};">${{s3}}</span>
                    <div class="top100-title">Video ID: ${{feat.properties.OBJECTID}}</div>
                    <div class="top100-desc">${{zone}} (Limit: ${{limit}} km/h)</div>
                    <div style="width: 100%; background: rgba(255,255,255,0.06); height: 4px; border-radius: 2px; margin-top: 8px; overflow: hidden;">
                        <div style="width: ${{s3Val}}%; background: ${{getScoreColor(s3Val)}}; height: 100%; border-radius: 2px;"></div>
                    </div>
                    ${{videoBtn}}
                `;
                
                if (lngLat) {{
                    item.onclick = () => flyToSegment(lngLat, feat.properties);
                }}
                videoEl.appendChild(item);
            }});
        }}
        
        function flyToSegment(lngLat, prop) {{
            map.flyTo({{ center: lngLat, zoom: 16, essential: true }});
        }}
        
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            event.target.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }}

        // Phase 54d: Smooth accordion using max-height CSS transitions
        function togglePopupSection(header) {{
            const content = header.nextElementSibling;
            const arrow = header.querySelector('.arrow');
            const isExpanded = content.classList.contains('expanded');
            if (!isExpanded) {{
                content.classList.add('expanded');
                arrow.style.transform = 'rotate(90deg)';
                arrow.style.transition = 'transform 0.25s ease';
            }} else {{
                content.classList.remove('expanded');
                arrow.style.transform = 'rotate(0deg)';
            }}
        }}
        
        {map_load_prefix}
        
        const map = new maplibregl.Map({{
            container: 'map',
            style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
            center: [{centroid.x}, {centroid.y}],
            zoom: 6
        }});

        map.on('error', (e) => {{
            console.error('MapLibre GL Error detail:', e.error ? e.error.stack : e);
            if (e.message) console.error('MapLibre GL Error message:', e.message);
        }});

        map.on('load', async () => {{
            await loadDashboardData();
            
            const svgXML = (shape, color) => {{
                let svg = '';
                if (shape === 'circle') svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="${{color}}" stroke="#fff" stroke-width="2"/></svg>`;
                else if (shape === 'square') svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" fill="${{color}}" stroke="#fff" stroke-width="2"/></svg>`;
                else if (shape === 'triangle') svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><polygon points="12,4 4,20 20,20" fill="${{color}}" stroke="#fff" stroke-width="2"/></svg>`;
                else if (shape === 'diamond') svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><polygon points="12,2 22,12 12,22 2,12" fill="${{color}}" stroke="#fff" stroke-width="2"/></svg>`;
                else if (shape === 'octagon') svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><polygon points="8.25,2 15.75,2 22,8.25 22,15.75 15.75,22 8.25,22 2,15.75 2,8.25" fill="${{color}}" stroke="#fff" stroke-width="2"/></svg>`;
                return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
            }};

            const hazardIcons = [
                {{ type: 'VRU', shape: 'octagon', color: '#ff9800' }},
                {{ type: 'V2V', shape: 'triangle', color: '#ff5252' }},
                {{ type: 'V2O', shape: 'diamond', color: '#ffeb3b' }},
                {{ type: 'PET', shape: 'octagon', color: '#ff9800' }}
            ];

            const loadIcons = () => {{
                const promises = hazardIcons.map(icon => {{
                    return new Promise((resolve) => {{
                        const img = new Image();
                        img.onload = () => {{
                            map.addImage('icon-' + icon.type, img);
                            resolve();
                        }};
                        img.src = svgXML(icon.shape, icon.color);
                    }});
                }});
                return Promise.all(promises);
            }};

            await loadIcons();

            map.addSource('road-network', {{
                type: 'geojson',
                data: geojsonData,
                promoteId: 'OBJECTID'
            }});
            
            // Dynamically generate infrastructure point features from road network lines
            const infraFeatures = [];
            geojsonData.features.forEach(f => {{
                const prop = f.properties;
                const geom = f.geometry;
                let coords = null;
                if (geom.type === 'LineString') {{
                    const idx = Math.floor(geom.coordinates.length / 2);
                    coords = geom.coordinates[idx];
                }} else if (geom.type === 'MultiLineString' && geom.coordinates.length > 0) {{
                    const line = geom.coordinates[0];
                    const idx = Math.floor(line.length / 2);
                    coords = line[idx];
                }}
                
                // Only create points if there's any actual infrastructure
                const crossings = Number(prop.OSM_Crossings_500m || 0) + Number(prop.Mapillary_Crosswalks || 0);
                const sidewalks = Number(prop.OSM_Sidewalks_500m || 0);
                const lighting = Number(prop.OSM_StreetLighting_500m || 0);
                const cycleways = Number(prop.OSM_Cycleways_500m || 0);
                const calming = Number(prop.OSM_TrafficCalming_500m || 0);
                const is_unpaved = String(prop.OSM_RoadSurface || '').toLowerCase() === 'unpaved';
                
                if (coords && (crossings > 0 || sidewalks > 0 || lighting > 0 || cycleways > 0 || calming > 0 || is_unpaved)) {{
                    // Determine dominant infrastructure type for display
                    let dominantType = 'None';
                    let color = '#ccc';
                    if (crossings > 0) {{ dominantType = 'Crossing'; color = '#ffeb3b'; }}
                    else if (sidewalks > 0) {{ dominantType = 'Sidewalk'; color = '#4caf50'; }}
                    else if (lighting > 0) {{ dominantType = 'Lighting'; color = '#2196f3'; }}
                    else if (cycleways > 0) {{ dominantType = 'Cycleway'; color = '#00bcd4'; }}
                    else if (calming > 0) {{ dominantType = 'Calming'; color = '#ff9800'; }}
                    else if (is_unpaved) {{ dominantType = 'Unpaved'; color = '#795548'; }}
                    
                    infraFeatures.push({{
                        type: 'Feature',
                        geometry: {{
                            type: 'Point',
                            coordinates: coords
                        }},
                        properties: {{
                            ...prop,
                            dominantType: dominantType,
                            pinColor: color
                        }}
                    }});
                }}
            }});
            const infraGeoJSON = {{
                type: 'FeatureCollection',
                features: infraFeatures
            }};

            map.addSource('infra-points', {{
                type: 'geojson',
                data: infraGeoJSON
            }});
            
            map.addSource('abm-conflicts', {{
                type: 'geojson',
                data: conflictData,
                cluster: true,
                clusterMaxZoom: 14,
                clusterRadius: 50
            }});

            // Infrastructure Pins Layer
            map.addLayer({{
                'id': 'infra-pins',
                'type': 'circle',
                'source': 'infra-points',
                'layout': {{
                    'visibility': 'visible'
                }},
                'paint': {{
                    'circle-color': ['get', 'pinColor'],
                    'circle-radius': 6,
                    'circle-stroke-color': '#ffffff',
                    'circle-stroke-width': 1.5,
                    'circle-opacity': 0.8
                }}
            }});

            // Priority Glow Layer (Thick)
            map.addLayer({{
                'id': 'priority-glow',
                'type': 'line',
                'source': 'road-network',
                'filter': ['<=', ['get', 'SpeedSafetyScore'], 30],
                'paint': {{
                    'line-color': '#FFD54F',
                    'line-width': 8,
                    'line-opacity': 0.3,
                    'line-blur': 4
                }}
            }});

            // Main Lines Layer (Data-Driven Styling)
            map.addLayer({{
                'id': 'road-lines',
                'type': 'line',
                'source': 'road-network',
                'layout': {{
                    'visibility': 'visible'
                }},
                'paint': {{
                    'line-width': [
                        'interpolate',
                        ['linear'],
                        ['get', 'SpeedSafetyScore'],
                        0, 4,
                        100, 1.5
                    ],
                    'line-color': [
                        'interpolate',
                        ['linear'],
                        ['get', 'SpeedSafetyScore'],
                        0, '#d73027',
                        10, '#f46d43',
                        20, '#fdae61',
                        30, '#fee08b',
                        40, '#ffd54f',
                        50, '#e6f598',
                        60, '#d9ef8b',
                        70, '#a6d96a',
                        80, '#66bd63',
                        90, '#1a9850',
                        100, '#006837'
                    ]
                }}
            }});

            // Safe System Violations Layer (Hidden by default)
            map.addLayer({{
                'id': 'safe-system-lines',
                'type': 'line',
                'source': 'road-network',
                'layout': {{
                    'visibility': 'none'
                }},
                'paint': {{
                    'line-width': [
                        'case',
                        ['==', ['get', 'SafeSystemAligned'], false], 5,
                        2
                    ],
                    'line-color': [
                        'case',
                        ['==', ['get', 'SafeSystemAligned'], false], '#FF5252',
                        '#4CAF50'
                    ]
                }}
            }});
            
            map.addLayer({{
                id: 'abm-clusters',
                type: 'circle',
                source: 'abm-conflicts',
                filter: ['has', 'point_count'],
                paint: {{
                    'circle-color': '#ff3d3d',
                    'circle-radius': 22,
                    'circle-stroke-color': '#fff',
                    'circle-stroke-width': 2,
                    'circle-opacity': 0.9
                }}
            }});

            map.addLayer({{
                id: 'abm-cluster-count',
                type: 'symbol',
                source: 'abm-conflicts',
                filter: ['has', 'point_count'],
                layout: {{
                    'text-field': '{{point_count_abbreviated}}',
                    'text-size': 12,
                    'text-allow-overlap': true,
                    'text-ignore-placement': true
                }},
                paint: {{
                    'text-color': '#fff'
                }}
            }});

            // Synthetic Conflict Layer (Custom Shapes, Z-Indexed to top)
            map.addLayer({{
                'id': 'abm-points',
                'type': 'symbol',
                'source': 'abm-conflicts',
                'filter': ['!', ['has', 'point_count']],
                'layout': {{
                    'icon-image': ['concat', 'icon-', ['get', 'type']],
                    'icon-size': 1.2,
                    'icon-allow-overlap': false,
                    'icon-ignore-placement': false
                }}
            }});

            // Layer Toggle Logic
            document.querySelectorAll('input[name="map-layer"]').forEach((radio) => {{
                radio.addEventListener('change', (e) => {{
                    const val = e.target.value;
                    if (val === 's3') {{
                        map.setLayoutProperty('road-lines', 'visibility', 'visible');
                        map.setLayoutProperty('priority-glow', 'visibility', 'visible');
                        map.setLayoutProperty('safe-system-lines', 'visibility', 'none');
                        document.getElementById('legend-s3').style.display = 'block';
                        document.getElementById('legend-safe').style.display = 'none';
                    }} else if (val === 'safe') {{
                        map.setLayoutProperty('road-lines', 'visibility', 'none');
                        map.setLayoutProperty('priority-glow', 'visibility', 'none');
                        map.setLayoutProperty('safe-system-lines', 'visibility', 'visible');
                        document.getElementById('legend-s3').style.display = 'none';
                        document.getElementById('legend-safe').style.display = 'block';
                    }}
                }});
            }});
            
            document.getElementById('layer-abm').addEventListener('change', (e) => {{
                const vis = e.target.checked ? 'visible' : 'none';
                map.setLayoutProperty('abm-points', 'visibility', vis);
                map.setLayoutProperty('abm-clusters', 'visibility', vis);
                map.setLayoutProperty('abm-cluster-count', 'visibility', vis);
            }});

            document.getElementById('layer-infra-pins').addEventListener('change', (e) => {{
                const vis = e.target.checked ? 'visible' : 'none';
                map.setLayoutProperty('infra-pins', 'visibility', vis);
            }});

            // Interactivity: Click for Popup on layers
            const interactLayers = ['road-lines', 'safe-system-lines', 'infra-pins'];
            
            interactLayers.forEach(layer => {{
                map.on('click', layer, (e) => {{
                    const prop = e.features[0].properties;
                    const s3 = prop.SpeedSafetyScore ? Number(prop.SpeedSafetyScore).toFixed(3) : '0.000';
                    const limit = prop.SpeedLimit !== undefined ? prop.SpeedLimit : '0';
                    const f85 = prop.F85thPercentileSpeed !== undefined ? Number(prop.F85thPercentileSpeed).toFixed(1) : '0.0';
                    const sub_supervisor = prop.SubSupervisorID || 'Unknown Overseer';
                    
                    const overtureLimit = prop.Overture_Maxspeed;
                    const speedLimitVal = Number(limit);
                    const overtureLimitVal = Number(overtureLimit);
                    const originalLimitVal = prop.OriginalSpeedLimit !== undefined ? Number(prop.OriginalSpeedLimit) : speedLimitVal;
                    let mismatchHtml = "";
                    if (overtureLimit && !isNaN(overtureLimitVal) && overtureLimitVal > 0 && overtureLimitVal !== originalLimitVal) {{
                        mismatchHtml = ` <span style="font-size:10px; background:#FFD54F; color:#111; padding:2px 4px; border-radius:3px; font-weight:bold; margin-left:5px; vertical-align:middle;">[!] Overture Mismatch: ${{overtureLimitVal}} km/h (Original: ${{originalLimitVal}} km/h)</span>`;
                    }}
                
                // Detailed 7 Rubric Categories
                const sKin = prop.Score_Kinematics !== undefined && prop.Score_Kinematics !== null ? Number(prop.Score_Kinematics).toFixed(3) : '0.000';
                const sFric = prop.Score_Friction !== undefined && prop.Score_Friction !== null ? Number(prop.Score_Friction).toFixed(3) : '0.000';
                const sVru = prop.Score_VRU !== undefined && prop.Score_VRU !== null ? Number(prop.Score_VRU).toFixed(3) : '0.000';
                const sSpd = prop.Score_Speeding !== undefined && prop.Score_Speeding !== null ? Number(prop.Score_Speeding).toFixed(3) : '0.000';
                const sExp = prop.Score_AI !== undefined && prop.Score_AI !== null ? Number(prop.Score_AI).toFixed(3) : '0.000';
                const sStr = prop.Score_Stress !== undefined && prop.Score_Stress !== null ? Number(prop.Score_Stress).toFixed(3) : '0.000';
                const sInf = prop.Score_Infrastructure !== undefined && prop.Score_Infrastructure !== null ? Number(prop.Score_Infrastructure).toFixed(3) : '0.000';
                
                // Max Weights
                const mKin = prop.Max_Kinematics !== undefined ? Number(prop.Max_Kinematics).toFixed(0) : '0';
                const mFric = prop.Max_Friction !== undefined ? Number(prop.Max_Friction).toFixed(0) : '0';
                const mVru = prop.Max_VRU !== undefined ? Number(prop.Max_VRU).toFixed(0) : '0';
                const mSpd = prop.Max_Speeding !== undefined ? Number(prop.Max_Speeding).toFixed(0) : '0';
                const mExp = prop.Max_AI !== undefined ? Number(prop.Max_AI).toFixed(0) : '0';
                const mStr = prop.Max_Stress !== undefined ? Number(prop.Max_Stress).toFixed(0) : '0';
                const mInf = prop.Max_Infrastructure !== undefined ? Number(prop.Max_Infrastructure).toFixed(0) : '0';

                // Imputed fields tracking helper
                const impCols = (prop.ImputedFields || "").split(",");
                const hasImp = impCols.length > 0 && impCols[0] !== "";
                const isImp = (f) => impCols.includes(f);
                const wrapVal = (val, f) => val + (isImp(f) ? " *" : "");

                // Intervention Cost and Safety ROI (Budget Mapping)
                const costVal = prop.Intervention_Cost !== undefined && prop.Intervention_Cost !== null ? Number(prop.Intervention_Cost) : 0;
                const roiVal = prop.Safety_ROI !== undefined && prop.Safety_ROI !== null ? Number(prop.Safety_ROI) : 0;
                
                const costHtml = costVal > 0 ? '$' + costVal.toLocaleString() : '$0 (No intervention proposed)';
                const roiHtml = costVal > 0 ? roiVal.toFixed(2) + ' pts per $10k' : '0.00 pts per $10k';

                const aiAdjust = prop.AI_Score_Adjustment !== undefined ? Number(prop.AI_Score_Adjustment) : 0.0;
                const aiAdjustHtml = aiAdjust !== 0.0
                    ? ` <span style="font-size:12px; font-weight:bold; color:${{aiAdjust < 0 ? '#d32f2f' : '#2e7d32'}};">(${{aiAdjust < 0 ? '' : '+'}}${{aiAdjust.toFixed(3)}} pts AI Tweak)</span>`
                    : '';

                const intervention = prop.AI_SpeedIntervention || 'No speed intervention recommended';
                const zone_type = prop.InferredZone || 'Generic Road';
                
                // ADB Raw Telemetry
                const rp = prop.RankedPercentile !== undefined && prop.RankedPercentile !== null ? Number(prop.RankedPercentile).toFixed(2) : '0.00';
                const ms = prop.MedianSpeed !== undefined && prop.MedianSpeed !== null ? Number(prop.MedianSpeed).toFixed(1) : '0.0';
                const nol = prop.PercentOverLimit !== undefined && prop.PercentOverLimit !== null ? Number(prop.PercentOverLimit).toFixed(1) + '%' : '0.0%';
                const ssa = prop.SampleSize_avg !== undefined && prop.SampleSize_avg !== null ? Number(prop.SampleSize_avg).toFixed(0) : '0';
                
                // ABM Hazard Context - specific counts
                const vruConflicts = prop.SegmentConflicts_VRU !== undefined ? Number(prop.SegmentConflicts_VRU).toFixed(1) : '0.0';
                const v2vConflicts = prop.SegmentConflicts_V2V !== undefined ? Number(prop.SegmentConflicts_V2V).toFixed(1) : '0.0';
                const v2oConflicts = prop.SegmentConflicts_V2O !== undefined ? Number(prop.SegmentConflicts_V2O).toFixed(1) : '0.0';
                const abmPets = prop.SegmentPETs !== undefined ? Number(prop.SegmentPETs).toFixed(1) : '0.0';
                const effHazards = prop.EffectiveHazards_VRU !== undefined ? Number(prop.EffectiveHazards_VRU).toFixed(1) : '0.0';
                const stressEvents = prop.ABM_Stress_Events !== undefined ? Number(prop.ABM_Stress_Events).toFixed(1) : '0.0';
                
                // Safe System Status
                const isSafeSystem = prop.SafeSystemAligned;
                const safeSystemHtml = isSafeSystem === true 
                    ? `<span style="color:#66bb6a; font-weight:bold;">Yes</span>` 
                    : `<span style="color:#ff5252; font-weight:bold;">No (VRU Hazard)</span>`;
                    
                const violatedRules = prop.Violated_Rules || "None";
                const violatedRulesHtml = violatedRules !== "None" 
                    ? `<br><b>Violated Rules:</b> <span style="color:#F44336; font-weight:bold;">${{violatedRules}}</span>` 
                    : "";                
                
                // What-If Details
                const whatIfDetails = prop.WhatIf_Action_Details;
                const whatIfHtml = whatIfDetails && whatIfDetails !== "None" ? `<hr style="margin:5px 0; border-top:1px solid #ddd;"><b>Simulated What-If Intervention:</b><br><span style="font-size:11px; color:#0288D1;">${{whatIfDetails}}</span>` : '';

                const isValid = (val) => val !== undefined && val !== null && val !== 'NaN' && !Number.isNaN(Number(val));
                
                // Spatial & Demographic Context
                const popDensity = isValid(prop.PopDensity_100m) ? Number(prop.PopDensity_100m).toFixed(0) + ' / km²' : 'N/A';
                const bldgDensity = isValid(prop.BuildingDensity_100m) ? Number(prop.BuildingDensity_100m).toFixed(1) + '%' : 'N/A';
                const urbanPop = isValid(prop.UrbanCentre_Pop) ? Number(prop.UrbanCentre_Pop).toLocaleString() : 'N/A';
                const poiSchools = isValid(prop.POI_Schools_500m) ? prop.POI_Schools_500m : 'N/A';
                const mapillarySigns = isValid(prop.Mapillary_TrafficSigns) ? prop.Mapillary_TrafficSigns : 'N/A';

                // Markings & Infrastructure
                const mapCrosswalks = isValid(prop.Mapillary_Crosswalks) ? prop.Mapillary_Crosswalks : 'N/A';
                const osmCrossings = isValid(prop.OSM_Crossings_500m) ? prop.OSM_Crossings_500m : 'N/A';
                const osmLighting = isValid(prop.OSM_StreetLighting_500m) ? prop.OSM_StreetLighting_500m : 'N/A';
                const osmCycleways = isValid(prop.OSM_Cycleways_500m) ? prop.OSM_Cycleways_500m : 'N/A';
                const osmSidewalks = isValid(prop.OSM_Sidewalks_500m) ? prop.OSM_Sidewalks_500m : 'N/A';
                
                const spatialHtml = `<div class="popup-header-toggle" onclick="togglePopupSection(this)">
                      <span>Spatial Context</span>
                      <span class="arrow" style="font-size: 10px;">&#9656;</span>
                    </div>
                    <div class="popup-section-content" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 10px; border-radius: 8px; margin-top: 6px;">
                      <table style="width:100%; font-size:11px; border-collapse:collapse; color:#90a4ae;">
                        <tr><td style="padding:3px 0;">Population Density:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{popDensity}}</td></tr>
                        <tr><td style="padding:3px 0;">Building Density:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{bldgDensity}}</td></tr>
                        <tr><td style="padding:3px 0;">Urban Centre Pop:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{urbanPop}}</td></tr>
                        <tr><td style="padding:3px 0;">Schools (500m):</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{poiSchools}}</td></tr>
                      </table>
                    </div>`;
 
                const markingsHtml = `<div class="popup-header-toggle" onclick="togglePopupSection(this)">
                      <span>Infrastructure & Markings</span>
                      <span class="arrow" style="font-size: 10px;">&#9656;</span>
                    </div>
                    <div class="popup-section-content" style="background: rgba(0,229,255,0.02); border: 1px solid rgba(0,229,255,0.08); padding: 10px; border-radius: 8px; margin-top: 6px;">
                      <table style="width:100%; font-size:11px; border-collapse:collapse; color:#90a4ae;">
                        <tr><td style="padding:3px 0;">Traffic Signs:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{mapillarySigns}}</td></tr>
                        <tr><td style="padding:3px 0;">Crosswalks:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{mapCrosswalks}}</td></tr>
                        <tr><td style="padding:3px 0;">OSM Crossings:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{osmCrossings}}</td></tr>
                        <tr><td style="padding:3px 0;">Street Lighting:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{osmLighting}}</td></tr>
                        <tr><td style="padding:3px 0;">Cycleways:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{osmCycleways}}</td></tr>
                        <tr><td style="padding:3px 0;">Sidewalks:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{osmSidewalks}}</td></tr>
                      </table>
                    </div>`;
 
                const footnoteHtml = hasImp ? `<div style="font-size:10px; color:#ef5350; font-style:italic; margin-top:8px; padding:6px 10px; background:rgba(239,83,80,0.08); border-radius:6px;">* Value imputed from spatial neighbors or regional context.</div>` : '';
 
                let html = `<div style="color:#eceff1; font-family:'Inter',sans-serif; font-size:12px; max-height:420px; overflow-y:auto; padding:16px;">
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
                        <h4 style="margin:0; color:#ff9800; font-family:'Outfit',sans-serif; font-size:15px; font-weight:600;">Segment Analysis</h4>
                        <span style="font-size:20px; font-weight:700; color:${{s3 <= 30 ? '#ff5252' : '#66bb6a'}};">${{s3}}</span>
                    </div>
                    <div style="font-size:10px; font-weight:600; color:#8a9ba8; text-align:right;" title="Pre-curve physics-based raw score">Raw Calculation: ${{prop.SpeedSafetyScore_PreShipRaw !== undefined ? Number(prop.SpeedSafetyScore_PreShipRaw).toFixed(1) : 'N/A'}}</div>
                    <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;">
                        <span style="font-size:9px; color:#0b1117; background:#00e5ff; padding:2px 7px; border-radius:10px; font-weight:600;">${{sub_supervisor}}</span>
                        <span style="font-size:9px; color:#0b1117; background:#ff9800; padding:2px 7px; border-radius:10px; font-weight:600;">${{zone_type}}</span>
                    </div>
                    
                    <div style="font-size:11px; color:#90a4ae; margin-bottom:10px;">
                        ${{s3 <= 30 ? '<span style="color:#ff9800; font-weight:bold;">[PRIORITY]</span> Segment recommended for speed and infrastructure review' : '<span style="color:#66bb6a; font-weight:bold;">[MONITOR]</span> No immediate modelled intervention priority'}}${{aiAdjustHtml}}
                    </div>
                    
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:10px;">
                        <div style="background:rgba(255,255,255,0.04); padding:8px; border-radius:6px; text-align:center;">
                            <div style="font-size:10px; color:#78909c; text-transform:uppercase; letter-spacing:0.5px;">Limit</div>
                            <div style="font-size:14px; font-weight:600; color:#eceff1;">${{wrapVal(limit, 'SpeedLimit')}} <span style="font-size:10px; color:#78909c;">km/h</span></div>
                        </div>
                        <div style="background:rgba(255,255,255,0.04); padding:8px; border-radius:6px; text-align:center;">
                            <div style="font-size:10px; color:#78909c; text-transform:uppercase; letter-spacing:0.5px;">85th Pct</div>
                            <div style="font-size:14px; font-weight:600; color:${{Number(f85) > Number(limit) ? '#ff5252' : '#eceff1'}};">${{wrapVal(f85, 'F85thPercentileSpeed')}} <span style="font-size:10px; color:#78909c;">km/h</span></div>
                        </div>
                    </div>
                    ${{mismatchHtml ? '<div style="margin-bottom:8px;">' + mismatchHtml + '</div>' : ''}}
                    
                    <b style="color:#b0bec5;">Safe System:</b> ${{safeSystemHtml}}${{violatedRulesHtml}}
                    
                    <div class="popup-header-toggle" onclick="togglePopupSection(this)">
                        <span>Rubric Breakdown</span>
                        <span class="arrow" style="font-size: 10px;">&#9656;</span>
                    </div>
                    <div class="popup-section-content">
                        <table style="width:100%; font-size:11px; border-collapse:collapse; color:#90a4ae; margin-top:4px;">
                            <tr><td style="padding:3px 0;">Kinematics:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{sKin}} / ${{mKin}}</td></tr>
                            <tr><td style="padding:3px 0;">Visual Friction:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{sFric}} / ${{mFric}}</td></tr>
                            <tr><td style="padding:3px 0;">VRU Risk:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{sVru}} / ${{mVru}}</td></tr>
                            <tr><td style="padding:3px 0;">Speeding Rate:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{sSpd}} / ${{mSpd}}</td></tr>
                            <tr><td style="padding:3px 0;">AI Review:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{sExp}} / ${{mExp}}</td></tr>
                            <tr><td style="padding:3px 0;">Active Stress:</td><td style="text-align:right; font-weight:600; color:#eceff1;">${{sStr}} / ${{mStr}}</td></tr>
                            <tr><td style="padding:3px 0;">Infrastructure:</td><td style="text-align:right; font-weight:600; color:#00e5ff;">${{sInf}} / ${{mInf}}</td></tr>
                        </table>
                    </div>
                    
                    <hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.06);">
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px;">
                        <div style="background:rgba(255,82,82,0.08); padding:8px; border-radius:6px; border-left:3px solid #ff5252;">
                            <div style="font-size:9px; color:#78909c; text-transform:uppercase;">Est. Cost</div>
                            <div style="font-size:12px; font-weight:600; color:#ff5252;">${{costHtml}}</div>
                        </div>
                        <div style="background:rgba(102,187,106,0.08); padding:8px; border-radius:6px; border-left:3px solid #66bb6a;">
                            <div style="font-size:9px; color:#78909c; text-transform:uppercase;">Safety ROI</div>
                            <div style="font-size:12px; font-weight:600; color:#66bb6a;">${{roiHtml}}</div>
                        </div>
                    </div>
                    
                    <div style="font-size:11px; color:#78909c; margin-bottom:10px;">
                        Median: ${{wrapVal(ms, 'MedianSpeed')}} km/h &bull; Percentile: ${{wrapVal(rp, 'RankedPercentile')}} &bull; Speeders: ${{wrapVal(nol, 'PercentOverLimit')}}
                    </div>
                    
                    <div class="popup-header-toggle" onclick="togglePopupSection(this)">
                        <span>ABM Conflicts</span>
                        <span class="arrow" style="font-size: 10px;">&#9656;</span>
                    </div>
                    <div class="popup-section-content" style="background:rgba(255,152,0,0.04); border:1px solid rgba(255,152,0,0.12); padding:10px; border-radius:8px;">
                      <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin-top:2px;">
                        <div style="text-align:center;"><div style="font-size:14px; font-weight:700; color:#e040fb;">${{vruConflicts}}</div><div style="font-size:9px; color:#78909c;">VRU</div></div>
                        <div style="text-align:center;"><div style="font-size:14px; font-weight:700; color:#ff5252;">${{v2vConflicts}}</div><div style="font-size:9px; color:#78909c;">V2V</div></div>
                        <div style="text-align:center;"><div style="font-size:14px; font-weight:700; color:#40c4ff;">${{v2oConflicts}}</div><div style="font-size:9px; color:#78909c;">V2O</div></div>
                      </div>
                      <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin-top:6px; border-top:1px solid rgba(255,152,0,0.15); padding-top:6px;">
                        <div style="text-align:center;"><div style="font-size:14px; font-weight:700; color:#ffab40;">${{abmPets}}</div><div style="font-size:9px; color:#78909c;">PET</div></div>
                        <div style="text-align:center;"><div style="font-size:14px; font-weight:700; color:#ff9800;">${{stressEvents}}</div><div style="font-size:9px; color:#78909c;">Stress</div></div>
                        <div style="text-align:center;"><div style="font-size:14px; font-weight:700; color:#ffc107;">${{effHazards}}</div><div style="font-size:9px; color:#78909c;">Hazard Wt</div></div>
                      </div>
                    </div>
                    
                    ${{spatialHtml}}
                    ${{markingsHtml}}
                    
                    <hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.06);">
                    <b style="color:#b0bec5; font-size:11px;">AI Recommendation:</b><br>
                    <span style="font-size:11px; color:#90a4ae; font-style:italic;">${{intervention}}</span>
                    ${{whatIfHtml}}
                    ${{footnoteHtml}}
                    ${{frameData[prop.OBJECTID] ? `<button onclick="event.stopPropagation(); playSimulation('${{prop.OBJECTID}}')" style="margin-top:12px; width:100%; padding:10px 14px; background:linear-gradient(135deg, #00acc1, #00838f); color:#fff; border:none; border-radius:8px; cursor:pointer; font-weight:600; font-family:'Outfit',sans-serif; font-size:12px; letter-spacing:0.3px; box-shadow:0 4px 15px rgba(0,172,193,0.3); transition:transform 0.2s ease;">&#9654; Play ABM Simulation</button>` : ''}}
                </div>`;

                new maplibregl.Popup({{ maxWidth: '320px' }})
                    .setLngLat(e.lngLat)
                    .setHTML(html)
                    .addTo(map);
                }});

                // Cursor styling
                map.on('mouseenter', layer, () => {{
                    map.getCanvas().style.cursor = 'pointer';
                }});
                map.on('mouseleave', layer, () => {{
                    map.getCanvas().style.cursor = '';
                }});
            }});
            
            // ABM Marker Popups
            map.on('click', 'abm-points', (e) => {{
                const prop = e.features[0].properties;
                const type = prop.type;
                const ttc = (prop.ttc !== undefined && prop.ttc !== null) ? Number(prop.ttc).toFixed(2) : '0.00';
                const pet = (prop.pet !== undefined && prop.pet !== null) ? Number(prop.pet).toFixed(2) : '0.00';
                
                let title = type === 'PET' ? 'Near Miss (PET)' : `Simulated Conflict (${{type}})`;
                let color = type === 'VRU' ? '#e040fb' : type === 'V2V' ? '#ff5252' : type === 'V2O' ? '#40c4ff' : '#ffab40';
                
                let html = `<div style="color:#eceff1; font-family:'Inter',sans-serif; font-size:12px; max-width:260px; padding:14px;">
                    <h4 style="margin:0 0 6px 0; color:${{color}}; font-family:'Outfit',sans-serif;">${{title}}</h4>
                    <span style="font-size:9px; color:#0b1117; background:${{color}}; padding:2px 7px; border-radius:10px; font-weight:600;">Synthetic Actor Interaction</span>
                    <hr style="margin:8px 0; border:0; border-top:1px solid rgba(255,255,255,0.06);">
                    ${{type !== 'PET' ? `<b style="color:#b0bec5;">Time-To-Collision:</b> <span style="font-weight:700; color:#eceff1;">${{ttc}}s</span><br>` : `<b style="color:#b0bec5;">Post-Encroachment Time:</b> <span style="font-weight:700; color:#eceff1;">${{pet}}s</span><br>`}}
                    <div style="font-size:10px; color:#78909c; margin-top:8px; line-height:1.5; background:rgba(255,255,255,0.03); padding:8px 10px; border-radius:6px; border:1px solid rgba(255,255,255,0.06);">
                        This simulated event indicates a modelled conflict detected by the ABM and contributes to the MKNS review priority.
                    </div>
                </div>`;

                new maplibregl.Popup({{ maxWidth: '300px' }})
                    .setLngLat(e.lngLat)
                    .setHTML(html)
                    .addTo(map);
            }});
            
            map.on('mouseenter', 'abm-points', () => {{ map.getCanvas().style.cursor = 'pointer'; }});
            map.on('mouseleave', 'abm-points', () => {{ map.getCanvas().style.cursor = ''; }});
            
            // Initialize the UI elements
            initTop100();
             // Draw Score Histogram
            if (geojsonData && geojsonData.features && document.getElementById('scoreChart')) {{
                const scores = geojsonData.features.map(f => f.properties.SpeedSafetyScore).filter(s => s !== undefined && s !== null);
                const bins = new Array(10).fill(0);
                scores.forEach(s => {{
                    let bin = Math.floor(s / 10);
                    if (bin > 9) bin = 9;
                    if (bin >= 0) bins[bin]++;
                }});
                const ctx = document.getElementById('scoreChart').getContext('2d');
                const barColors = ['#800026','#d32f2f','#e65100','#f57f17','#fbc02d','#c0ca33','#7cb342','#43a047','#2e7d32','#006837'];
                new Chart(ctx, {{
                    type: 'bar',
                    data: {{
                        labels: ['0-10', '10-20', '20-30', '30-40', '40-50', '50-60', '60-70', '70-80', '80-90', '90-100'],
                        datasets: [{{
                            label: 'Segments',
                            data: bins,
                            backgroundColor: barColors,
                            borderRadius: 3,
                            borderSkipped: false,
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            legend: {{ display: false }},
                            title: {{ display: true, text: 'MKNS Score Distribution', color: '#b0bec5', font: {{ family: "'Inter', sans-serif", size: 10, weight: 500 }} }}
                        }},
                        scales: {{
                            y: {{ ticks: {{ color: '#78909c', font: {{ family: "'Inter', sans-serif", size: 8 }} }}, grid: {{ color: 'rgba(255,255,255,0.04)' }} }},
                            x: {{ ticks: {{ color: '#78909c', font: {{ family: "'Inter', sans-serif", size: 8 }} }}, grid: {{ display: false }} }}
                        }}
                    }}
                }});
            }}
        }});

        // --- Draggable Widget Logic ---
        function makeDraggable(elmnt) {{
            var pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
            elmnt.onmousedown = dragMouseDown;

            function dragMouseDown(e) {{
                e = e || window.event;
                // Prevent dragging when clicking inputs or labels inside the legend
                if (e.target.tagName.toLowerCase() === 'input' || e.target.tagName.toLowerCase() === 'label') return;
                e.preventDefault();
                pos3 = e.clientX;
                pos4 = e.clientY;
                document.onmouseup = closeDragElement;
                document.onmousemove = elementDrag;
            }}

            function elementDrag(e) {{
                e = e || window.event;
                e.preventDefault();
                pos1 = pos3 - e.clientX;
                pos2 = pos4 - e.clientY;
                pos3 = e.clientX;
                pos4 = e.clientY;
                elmnt.style.top = (elmnt.offsetTop - pos2) + "px";
                elmnt.style.left = (elmnt.offsetLeft - pos1) + "px";
                // Remove bottom/right constraints so top/left can drive placement
                elmnt.style.bottom = "auto";
                elmnt.style.right = "auto";
            }}

            function closeDragElement() {{
                document.onmouseup = null;
                document.onmousemove = null;
            }}
        }}

        // Make both legends movable
        const hazardLegendEl = document.getElementById("hazard-legend");
        if (hazardLegendEl) makeDraggable(hazardLegendEl);
        const legendEl = document.getElementById("legend");
        if (legendEl) makeDraggable(legendEl);
    </script>
</body>
</html>
"""
        with open(output_html, "w", encoding="utf-8") as f:
            if external_data:
                f.write(html_content)
            else:
                parts = html_content.split("__JSON_SCRIPTS_PLACEHOLDER__")
                f.write(parts[0])
                f.write('<script id="geojson-data-src" type="application/json">')
                f.write(geojson_str)
                f.write('</script>\n')
                f.write('<script id="conflict-data-src" type="application/json">')
                f.write(conflict_geojson_str)
                f.write('</script>\n')
                f.write(parts[1])

        print(f"MapLibre GL map generated at: {output_html}")
