import os
import sys
import json
import geopandas as gpd
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from prototypes.geospatial_model.map_generator import MapGenerator

def backfill_insights():
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except ImportError:
        print("Error: The 'google-genai' package is not installed. Please run: pip install google-genai")
        return

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    geojson_path = os.path.join(base_dir, 'makenes_scored.geojson')
    
    if not os.path.exists(geojson_path):
        print(f"Error: Could not find {geojson_path}. Ensure the main pipeline has finished.")
        return

    print("Loading network geojson...")
    gdf = gpd.read_file(geojson_path)
    
    # We need to extract archetypes to avoid spamming the LLM
    # In main.py, archetypes are stored in 'Archetype'
    if 'Archetype' not in gdf.columns:
        print("Error: Archetype column missing from GeoJSON.")
        return
        
    unique_archetypes = gdf['Archetype'].unique()
    print(f"Found {len(unique_archetypes)} unique archetypes to evaluate.")
    
    # Build prompt
    prompt = (
        "You are a Board of Evaluators for a road safety digital twin.\n"
        "Provide a 1-2 sentence systemic policy intervention for each road archetype.\n"
        "Base your response on the provided preliminary analysis and domain.\n\n"
    )
    
    # We only have limited data in the geojson compared to the raw dataframe, but we can reconstruct it
    for arch_id in unique_archetypes:
        sample = gdf[gdf['Archetype'] == arch_id].iloc[0]
        context = sample.get('AI_SpeedIntervention', '')
        prompt += f"Archetype {arch_id} | Context: {context}\n"
        
    schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            str(arch_id): types.Schema(type=types.Type.STRING) for arch_id in unique_archetypes
        }
    )
    
    print("Requesting GenAI dynamic rationales (Batched)...")
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            )
        )
        genai_interventions = json.loads(response.text)
        print("Successfully received AI insights.")
    except Exception as e:
        print(f"Failed to get AI insights: {e}")
        return

    # Update GeoJSON
    def update_intervention(row):
        arch_id = row['Archetype']
        base = row.get('AI_SpeedIntervention', '')
        insight = genai_interventions.get(arch_id, genai_interventions.get(str(arch_id)))
        if insight and "[AI Insight" not in str(base):
            return f"{base} [AI Insight: {insight}]"
        return base

    print("Injecting insights into network...")
    gdf['AI_SpeedIntervention'] = gdf.apply(update_intervention, axis=1)
    
    # Save geojson
    print("Saving updated GeoJSON...")
    gdf.to_file(geojson_path, driver='GeoJSON')
    
    # Regenerate Map
    print("Regenerating MapLibre Dashboard...")
    # Load conflicts and frames if possible, or just generate without if we don't have them
    # Wait, the MapGenerator needs conflicts and frames to be fully complete.
    # But since this is a backfill, let's just use what's in the DB.
    from agents.database_manager import DatabaseManager
    db_path = os.path.join(base_dir, 'db', 'makenes.sqlite')
    db_manager = DatabaseManager(db_path)
    
    import sqlite3
    conflict_gdf = gpd.GeoDataFrame(columns=['geometry', 'type', 'segment_id'], crs="EPSG:4326")
    try:
        conn = sqlite3.connect(db_path)
        conflict_df = pd.read_sql_query("SELECT * FROM abm_conflicts_global", conn)
        from shapely import wkt
        if 'geometry' in conflict_df.columns:
            conflict_df['geometry'] = conflict_df['geometry'].apply(wkt.loads)
            conflict_gdf = gpd.GeoDataFrame(conflict_df, geometry='geometry', crs="EPSG:4326")
        conn.close()
    except Exception as e:
        print("Warning: Could not load conflicts for map regeneration.")
        
    map_gen = MapGenerator(gdf, conflict_gdf=conflict_gdf)
    output_html = os.path.join(base_dir, 'makenes_safety_map.html')
    map_gen.generate_map(output_html=output_html, output_geojson=geojson_path)
    print(f"Done! Updated map saved to: {output_html}")

if __name__ == "__main__":
    backfill_insights()
