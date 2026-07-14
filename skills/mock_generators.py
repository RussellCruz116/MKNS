import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from typing import List, Tuple, Dict

def generate_log_normal_speeds(mean_speed_kmh: float, std_dev_kmh: float, count: int) -> np.ndarray:
    """
    Generates a distribution of synthetic vehicle speeds using Inverse Transform Sampling
    from a log-normal distribution, mimicking real GPS probe telemetry.
    """
    # Calculate the underlying normal distribution parameters (mu, sigma)
    # var = std_dev^2
    # mu = ln(mean^2 / sqrt(var + mean^2))
    # sigma = sqrt(ln(1 + (var / mean^2)))
    
    variance = std_dev_kmh ** 2
    mu = np.log((mean_speed_kmh ** 2) / np.sqrt(variance + mean_speed_kmh ** 2))
    sigma = np.sqrt(np.log(1 + (variance / (mean_speed_kmh ** 2))))
    
    speeds = np.random.lognormal(mean=mu, sigma=sigma, size=count)
    return speeds

def generate_mock_pois(bounding_box: Tuple[float, float, float, float], count: int, poi_types: List[str] = None) -> gpd.GeoDataFrame:
    """
    Generates mock Mapillary/OpenStreetMap Point of Interest (POI) data.
    Bounding box format: (min_lon, min_lat, max_lon, max_lat)
    """
    if poi_types is None:
        poi_types = ['school', 'crosswalk', 'market', 'bus_stop']
        
    min_lon, min_lat, max_lon, max_lat = bounding_box
    
    # Generate random points within bounding box
    lons = np.random.uniform(min_lon, max_lon, count)
    lats = np.random.uniform(min_lat, max_lat, count)
    
    points = [Point(lon, lat) for lon, lat in zip(lons, lats)]
    types = np.random.choice(poi_types, count)
    
    # Create GeoDataFrame, assuming WGS84
    gdf = gpd.GeoDataFrame({'poi_type': types}, geometry=points, crs="EPSG:4326")
    return gdf

def generate_mock_gps_probe_data(edge_ids: List[int]) -> pd.DataFrame:
    """
    Assigns mock 85th percentile and mean speeds to a list of network edges.
    """
    data = []
    for edge_id in edge_ids:
        mean_speed = np.random.uniform(30.0, 70.0) # Mock mean speed between 30 and 70 km/h
        std_dev = np.random.uniform(5.0, 15.0)
        
        speeds = generate_log_normal_speeds(mean_speed, std_dev, 100)
        speed_85th = np.percentile(speeds, 85)
        
        data.append({
            'edge_id': edge_id,
            'mean_speed_kmh': mean_speed,
            'speed_85th_kmh': speed_85th,
            'std_dev_kmh': std_dev
        })
        
    return pd.DataFrame(data)
