import geopandas as gpd

def snap_pois_to_edges(pois_gdf: gpd.GeoDataFrame, edges_gdf: gpd.GeoDataFrame, buffer_radius_m: float = 15.0) -> gpd.GeoDataFrame:
    """
    Fuses spatial POIs into road segments using a buffer intersection.
    Assumes inputs are in a projected (meter-based) CRS like UTM.
    """
    if pois_gdf.crs != edges_gdf.crs:
        raise ValueError("CRS mismatch between POIs and edges. Both must be in the same projected CRS.")
        
    # Create a spatial buffer around the road edge line-strings
    edges_buffered = edges_gdf.copy()
    edges_buffered['geometry'] = edges_gdf.geometry.buffer(buffer_radius_m)
    
    # Execute spatial join to map POIs into road segments
    fused_data = gpd.sjoin(pois_gdf, edges_buffered, predicate='within')
    return fused_data
