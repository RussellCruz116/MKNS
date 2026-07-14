import geopandas as gpd
import folium
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_safety_map(geojson_path: str, output_html: str):
    logger.info(f"Loading scored network from {geojson_path}")
    if not os.path.exists(geojson_path):
        logger.error("Scored GeoJSON not found. Please run evaluator_agent.py first.")
        return
        
    gdf = gpd.read_file(geojson_path)
    
    # Ensure CRS is correct for Folium (WGS84 EPSG:4326)
    if gdf.crs != "EPSG:4326":
        logger.info("Reprojecting to EPSG:4326 for web mapping.")
        gdf = gdf.to_crs("EPSG:4326")

    logger.info("Initializing Map...")
    # Center map on the median coordinates of the dataset
    bounds = gdf.total_bounds # [minx, miny, maxx, maxy]
    center_lat = (bounds[1] + bounds[3]) / 2.0
    center_lon = (bounds[0] + bounds[2]) / 2.0
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles='CartoDB dark_matter')
    
    # Define a color scale for the Speed Safety Score (0-100)
    # Lower score (red/dangerous), Higher score (green/safe)
    def style_function(feature):
        score = feature['properties'].get('SpeedSafetyScore', 50)
        
        if score < 40:
            color = '#ff0000' # Red
        elif score < 70:
            color = '#ffa500' # Orange
        else:
            color = '#00ff00' # Green
            
        return {
            'color': color,
            'weight': 3,
            'opacity': 0.8
        }

    logger.info("Adding GeoJSON layer to map...")
    folium.GeoJson(
        gdf,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['english_ro', 'RoadClass', 'LandUse', 'SpeedLimit', 'F85thPercentileSpeed', 'SpeedSafetyScore'],
            aliases=['Street Name', 'Road Class', 'Land Use', 'Speed Limit (km/h)', '85th Percentile Speed (km/h)', 'Safety Score (1-100)'],
            localize=True
        )
    ).add_to(m)
    
    m.save(output_html)
    logger.info(f"Map successfully saved to {output_html}")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scored_file = os.path.join(base_dir, 'data', 'scored_network.geojson')
    output_file = os.path.join(base_dir, 'data', 'map.html')
    
    generate_safety_map(scored_file, output_file)
