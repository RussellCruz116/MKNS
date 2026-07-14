import os
import requests
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box, Point

class DataOrchestrator:
    def __init__(self, network_gdf: gpd.GeoDataFrame):
        self.network = network_gdf
        self.token = os.environ.get("MAPILLARY_ACCESS_TOKEN", "")

    def inject_mapillary_friction(self):
        """
        Queries Mapillary for visual friction elements (crosswalks, narrow paths)
        to augment the ABM physics engine.  If SpatialEnricher has already populated
        Mapillary_TrafficSigns / Mapillary_Crosswalks columns, performs a per-segment
        spatial join to derive friction.  Otherwise falls back to the heuristic.
        """
        print("[Data Orchestrator] Initializing Mapillary Context Injection...")
        
        # We add 'MapillaryVisualFriction' column
        if 'MapillaryVisualFriction' not in self.network.columns:
            self.network['MapillaryVisualFriction'] = 1.0

        # Phase 46: Check if SpatialEnricher already populated Mapillary columns
        has_enriched = (
            'Mapillary_TrafficSigns' in self.network.columns and
            'Mapillary_Crosswalks' in self.network.columns
        )

        if has_enriched:
            enriched_signs = pd.to_numeric(self.network['Mapillary_TrafficSigns'], errors='coerce').fillna(0)
            enriched_crosswalks = pd.to_numeric(self.network['Mapillary_Crosswalks'], errors='coerce').fillna(0)
            has_data = (enriched_signs.sum() > 0) or (enriched_crosswalks.sum() > 0)
        else:
            has_data = False

        if has_data:
            # Per-segment spatial friction from enriched Mapillary data
            print("[Data Orchestrator] Using SpatialEnricher Mapillary data for per-segment friction...")
            self._apply_enriched_mapillary_friction(enriched_signs, enriched_crosswalks)
            return self.network

        if not self.token:
            print("[WARNING] MAPILLARY_ACCESS_TOKEN is missing. Falling back to heuristic visual friction inference.")
            self._apply_heuristic_friction()
            return self.network

        try:
            # We don't want to spam the API for 50,000 segments, so we grab the global bounding box
            # and pull a sample of map features to statistically scale the region.
            bounds = self.network.total_bounds # [minx, miny, maxx, maxy]
            bbox_str = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
            
            print(f"   -> Querying Mapillary v4 API for bounding box: {bbox_str}...")
            url = f"https://graph.mapillary.com/map_features?access_token={self.token}&fields=id,value,geometry&bbox={bbox_str}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                features = data.get('data', [])
                print(f"   -> Successfully retrieved {len(features)} Mapillary map features.")
                
                if len(features) > 0:
                    # Build per-segment spatial join
                    self._spatial_join_mapillary_features(features)
                else:
                    api_density_multiplier = 1.0 + (len(features) / 1000.0)
                    self._apply_heuristic_friction(multiplier=api_density_multiplier)
            else:
                print(f"[WARNING] Mapillary API returned {response.status_code}. Falling back to heuristics.")
                self._apply_heuristic_friction()
                
        except Exception as e:
            print(f"[ERROR] Mapillary API failed: {e}. Using heuristics.")
            self._apply_heuristic_friction()

        return self.network

    def _apply_enriched_mapillary_friction(self, signs_series, crosswalks_series):
        """
        Phase 46: Derive per-segment visual friction from pre-enriched Mapillary columns.
        More traffic signs and crosswalks = more managed environment = higher friction
        (pedestrians expect safety, more stopping, more visual clutter).
        """
        def calc_enriched_friction(row):
            speed_limit = row.get('SpeedLimit', 50)
            land_use = row.get('LandUse', 'URBAN')
            road_class = row.get('RoadClass', 'secondary')
            signs = int(row.get('Mapillary_TrafficSigns', 0) or 0)
            crosswalks = int(row.get('Mapillary_Crosswalks', 0) or 0)
            
            # Base friction from road context
            friction = 1.0
            if speed_limit <= 30:
                friction = 1.5
            elif land_use == 'URBAN' and speed_limit <= 50:
                friction = 1.3
            elif land_use == 'URBAN' and road_class in ['primary', 'trunk'] and speed_limit > 50:
                friction = 1.1
            elif land_use == 'RURAL' and road_class not in ['motorway']:
                friction = 0.8
            elif road_class == 'motorway':
                friction = 0.5
            
            # Modulate with Mapillary evidence
            # More signs = more managed = slightly higher friction
            sign_mod = min(0.3, signs * 0.05)
            crosswalk_mod = min(0.3, crosswalks * 0.1)
            friction += sign_mod + crosswalk_mod
            
            return friction

        self.network['MapillaryVisualFriction'] = self.network.apply(calc_enriched_friction, axis=1)
        enriched_count = ((signs_series > 0) | (crosswalks_series > 0)).sum()
        print(f"   -> Applied per-segment Mapillary friction to {enriched_count} segments")

    def _spatial_join_mapillary_features(self, features):
        """
        Phase 46: Perform per-segment spatial join with live Mapillary API features.
        """
        # Build GeoDataFrame from features
        points = []
        for f in features:
            geom = f.get('geometry', {})
            coords = geom.get('coordinates', [])
            value = f.get('value', '')
            if coords:
                points.append({
                    'geometry': Point(coords[0], coords[1]),
                    'value': value,
                    'is_crosswalk': 'crosswalk' in value.lower() or 'pedestrian' in value.lower()
                })
        
        if not points:
            self._apply_heuristic_friction()
            return
            
        feat_gdf = gpd.GeoDataFrame(points, crs='EPSG:4326')
        
        # Buffer segments by ~200m for spatial join
        buffer_deg = 200.0 / 111320.0
        buffered = self.network[['geometry']].copy()
        buffered['geometry'] = buffered.geometry.buffer(buffer_deg)
        buffered['_idx'] = range(len(buffered))
        
        joined = gpd.sjoin(feat_gdf, buffered, predicate='within', how='inner')
        
        if not joined.empty:
            signs_per_seg = joined[~joined['is_crosswalk']].groupby('_idx').size()
            crosswalks_per_seg = joined[joined['is_crosswalk']].groupby('_idx').size()
            
            self.network['Mapillary_TrafficSigns'] = self.network.index.map(signs_per_seg).fillna(0).astype(int)
            self.network['Mapillary_Crosswalks'] = self.network.index.map(crosswalks_per_seg).fillna(0).astype(int)
            
            # Now derive friction from the joined data
            self._apply_enriched_mapillary_friction(
                self.network['Mapillary_TrafficSigns'],
                self.network['Mapillary_Crosswalks']
            )
        else:
            api_density_multiplier = 1.0 + (len(features) / 1000.0)
            self._apply_heuristic_friction(multiplier=api_density_multiplier)

    def _apply_heuristic_friction(self, multiplier=1.0):
        """ Applies inferred friction based on land use and road class (Phase 17 logic upgraded). """
        def calc_friction(row):
            speed_limit = row.get('SpeedLimit', 50)
            land_use = row.get('LandUse', 'URBAN')
            road_class = row.get('RoadClass', 'secondary')
            
            friction = 1.0
            if speed_limit <= 30:
                friction = 1.5
            elif land_use == 'URBAN' and speed_limit <= 50:
                friction = 1.3
            elif land_use == 'URBAN' and road_class in ['primary', 'trunk'] and speed_limit > 50:
                friction = 1.1
            elif land_use == 'RURAL' and road_class not in ['motorway']:
                friction = 0.8
            elif road_class == 'motorway':
                friction = 0.5
                
            return friction * multiplier

        self.network['MapillaryVisualFriction'] = self.network.apply(calc_friction, axis=1)
