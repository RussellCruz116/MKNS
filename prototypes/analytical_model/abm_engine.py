import mesa
# pyrefly: ignore [missing-import]
import mesa_geo as mg
from shapely.geometry import Point, LineString
import numpy as np
import random
import math
import os
import json


class BaseActor(mg.GeoAgent):
    """
    Base class for all ABM actors (Pedestrian, Car, PTW, HGV, Obstruction).
    Implements fundamental kinematics (velocity, acceleration) and manages
    1D geometry movement constrained along a LineString network.
    """
    def __init__(self, model, geometry, crs, line_geom, spawn_dist, actor_type="Car", road_class="secondary", segment_id=None, orig_lon=0.0, orig_lat=0.0):
        super().__init__(model, geometry, crs)
        self.actor_type = actor_type
        self.line_geom = line_geom
        self.distance_traveled = spawn_dist
        self.segment_id = segment_id
        self.orig_lon = orig_lon
        self.orig_lat = orig_lat
        self.road_class = road_class
        
        self.base_direction = 1.0
        self.heading_x = 1.0
        self.heading_y = 0.0
        self.is_night = False
        
        # Will be overridden
        self.velocity = 0
        self.acceleration = 0
        self.desired_speed = 0
        self.max_acceleration = 2.0
        self.base_geometry = geometry
        self.lateral_offset = 0.0

    def step(self):
        if self.actor_type == "Obstruction":
            return
            
        safe_max = max(1.0, self.desired_speed)
        
        if self.actor_type == "Pedestrian":
            # SFM logic
            calibrated_unpredictability = getattr(self, 'unpredictability', 0.1) * getattr(self, 'visual_friction', 1.0)
            if random.random() < calibrated_unpredictability:
                self.velocity = random.uniform(0.0, self.desired_speed * 1.5)
            else:
                self.velocity = self.desired_speed
            base_acceleration = 0
            stochastic_noise = 0
        else:
            # IDM logic
            base_acceleration = self.max_acceleration * (1 - (self.velocity / safe_max)**4)
            noise_level = getattr(self, 'noise_level', 0.2)
            stochastic_noise = np.random.normal(0, noise_level)
            
        self.acceleration = base_acceleration + stochastic_noise
        self.velocity = max(0, self.velocity + self.acceleration)
        
        meters_to_degrees = 1 / 111320.0
        dist_degrees = (self.velocity / 3.6) * meters_to_degrees
        
        if self.actor_type == "Pedestrian" and getattr(self, 'is_crossing', False):
            # Move laterally across the road
            self.lateral_offset += dist_degrees * getattr(self, 'base_direction', 1.0)
            road_width_deg = 5.0 * meters_to_degrees
            if self.lateral_offset > road_width_deg:
                self.lateral_offset = road_width_deg
                self.base_direction = -1.0
            elif self.lateral_offset < -road_width_deg:
                self.lateral_offset = -road_width_deg
                self.base_direction = 1.0
        else:
            # Move longitudinally
            direction = getattr(self, 'base_direction', 1.0)
            if self.actor_type == "Pedestrian" and random.random() < 0.2:
                direction = -direction
            self.distance_traveled += dist_degrees * direction
        
        # Constrain to line / perform cross-segment handoff
        if self.line_geom and self.line_geom.geom_type in ['LineString', 'MultiLineString']:
            reached_node = None
            if self.distance_traveled <= 0.0:
                if self.model.topology and self.segment_id in self.model.topology.segment_nodes:
                    reached_node = self.model.topology.segment_nodes[self.segment_id][0]  # start node
            elif self.distance_traveled >= self.line_geom.length:
                if self.model.topology and self.segment_id in self.model.topology.segment_nodes:
                    reached_node = self.model.topology.segment_nodes[self.segment_id][1]  # end node
                    
            if reached_node is not None:
                downstream = self.model.topology.get_downstream_for_node(reached_node, self.segment_id)
                available_downstream = [sid for sid in downstream if sid in self.model.segment_geometries]
                if available_downstream:
                    next_seg_id = random.choice(available_downstream)
                    next_seg_info = self.model.segment_geometries[next_seg_id]
                    next_geom = next_seg_info['geometry']
                    
                    next_nodes = self.model.topology.segment_nodes[next_seg_id]
                    if reached_node == next_nodes[0]:
                        self.base_direction = 1.0
                        self.distance_traveled = 0.0
                    else:
                        self.base_direction = -1.0
                        self.distance_traveled = next_geom.length
                        
                    self.segment_id = next_seg_id
                    self.line_geom = next_geom
                    self.road_class = next_seg_info['RoadClass']
                    self.base_geometry = self.line_geom.interpolate(self.distance_traveled)
                    self.geometry = self.base_geometry
                    
                    # Calculate new heading immediately
                    lookahead_dist = 1e-5
                    if self.base_direction == 1.0:
                        pt_ahead = self.line_geom.interpolate(min(self.line_geom.length, lookahead_dist))
                    else:
                        pt_ahead = self.line_geom.interpolate(max(0.0, self.line_geom.length - lookahead_dist))
                    dx = pt_ahead.x - self.base_geometry.x
                    dy = pt_ahead.y - self.base_geometry.y
                    dist = math.hypot(dx, dy)
                    if dist > 0:
                        self.heading_x = dx / dist
                        self.heading_y = dy / dist
                    return
                    
            # If no downstream segment is available, despawn the actor to prevent infinite accumulation
            self.despawn = True
            return
                    
            new_pt = self.line_geom.interpolate(self.distance_traveled)
            
            # calculate dynamic heading based on previous point
            dx = new_pt.x - getattr(self, 'base_geometry', self.geometry).x
            dy = new_pt.y - getattr(self, 'base_geometry', self.geometry).y
            dist = math.hypot(dx, dy)
            if dist > 0:
                self.heading_x = dx / dist
                self.heading_y = dy / dist
                
            self.base_geometry = new_pt
            
            lateral = getattr(self, 'lateral_offset', 0.0)
            if self.actor_type == "Pedestrian" and not getattr(self, 'is_crossing', False):
                # Sidewalk pedestrians have fixed lateral offset
                lateral = 4.0 * meters_to_degrees * (1 if getattr(self, 'sidewalk_side', 1) > 0 else -1)
                
            if lateral != 0.0:
                # Perpendicular vector is (-y, x)
                perp_x = -self.heading_y
                perp_y = self.heading_x
                new_x = new_pt.x + perp_x * lateral
                new_y = new_pt.y + perp_y * lateral
                self.geometry = Point(new_x, new_y)
            else:
                self.geometry = new_pt
        else:
            # Fallback 2D
            new_x = self.geometry.x + dist_degrees * self.heading_x
            new_y = self.geometry.y + dist_degrees * self.heading_y
            self.geometry = Point(new_x, new_y)

class CarActor(BaseActor):
    def __init__(self, model, geometry, crs, max_speed, line_geom, spawn_dist, road_class="secondary", segment_id=None, orig_lon=0.0, orig_lat=0.0, politeness=0.2, direction=1.0):
        super().__init__(model, geometry, crs, line_geom, spawn_dist, "Car", road_class, segment_id, orig_lon, orig_lat)
        self.base_direction = direction
        width_penalty = 0.7 if road_class in ['residential', 'tertiary', 'unclassified'] else 1.0
        self.max_speed = max_speed * width_penalty
        self.velocity = np.random.uniform(10, max(11, self.max_speed))
        self.desired_speed = self.max_speed
        self.safe_time_headway = 1.8
        self.max_acceleration = 2.0
        self.desired_deceleration = 1.8
        self.min_gap = 2.2
        self.politeness = politeness
        self.noise_level = 0.2

class PTWActor(BaseActor):
    def __init__(self, model, geometry, crs, max_speed, line_geom, spawn_dist, road_class="secondary", segment_id=None, orig_lon=0.0, orig_lat=0.0, politeness=0.05, direction=1.0):
        super().__init__(model, geometry, crs, line_geom, spawn_dist, "PTW", road_class, segment_id, orig_lon, orig_lat)
        self.base_direction = direction
        width_penalty = 0.8 if road_class in ['residential', 'tertiary', 'unclassified'] else 1.0
        self.max_speed = max_speed * width_penalty
        self.velocity = np.random.uniform(10, max(11, self.max_speed))
        self.desired_speed = self.max_speed
        self.safe_time_headway = 0.9
        self.max_acceleration = 3.5
        self.desired_deceleration = 4.0
        self.min_gap = 0.8
        self.politeness = politeness
        self.noise_level = 0.3

class HGVActor(BaseActor):
    def __init__(self, model, geometry, crs, max_speed, line_geom, spawn_dist, road_class="primary", segment_id=None, orig_lon=0.0, orig_lat=0.0, politeness=0.1, direction=1.0):
        super().__init__(model, geometry, crs, line_geom, spawn_dist, "HGV", road_class, segment_id, orig_lon, orig_lat)
        self.base_direction = direction
        width_penalty = 0.6 if road_class in ['residential', 'tertiary', 'unclassified'] else 1.0
        self.max_speed = min(max_speed * width_penalty, 80.0)
        self.velocity = np.random.uniform(10, max(11, self.max_speed))
        self.desired_speed = self.max_speed
        self.safe_time_headway = 2.5
        self.max_acceleration = 0.8
        self.desired_deceleration = 1.2
        self.min_gap = 3.0
        self.politeness = politeness
        self.noise_level = 0.1

class CyclistActor(BaseActor):
    """Simulates cyclists sharing the road edge / bike lane (VRU deliverable)."""
    def __init__(self, model, geometry, crs, line_geom, spawn_dist, segment_id=None, orig_lon=0.0, orig_lat=0.0, direction=1.0):
        super().__init__(model, geometry, crs, line_geom, spawn_dist, "Cyclist", "unknown", segment_id, orig_lon, orig_lat)
        self.base_direction = direction
        self.desired_speed = random.uniform(12.0, 22.0)
        self.velocity = self.desired_speed
        self.max_acceleration = 1.2
        # Bike-lane offset (~1.5 m from centerline)
        meters_to_degrees = 1 / 111320.0
        self.lateral_offset = 1.5 * meters_to_degrees * (1 if direction > 0 else -1)

class PedestrianActor(BaseActor):
    def __init__(self, model, geometry, crs, line_geom, spawn_dist, segment_id=None, orig_lon=0.0, orig_lat=0.0, repulsion_strength=2.0, visual_friction=1.0, is_crossing=False):
        super().__init__(model, geometry, crs, line_geom, spawn_dist, "Pedestrian", "unknown", segment_id, orig_lon, orig_lat)
        self.visual_friction = visual_friction
        self.is_crossing = is_crossing
        self.sidewalk_side = 1 if random.random() < 0.5 else -1
        if self.is_crossing:
            self.lateral_offset = 5.0 * (1 / 111320.0) * self.sidewalk_side
            self.base_direction = -self.sidewalk_side
        self.ped_profile = random.choices(["Adult", "Child", "Elderly", "Distracted"], weights=[0.5, 0.2, 0.1, 0.2])[0]
        if self.ped_profile == "Adult":
            self.desired_speed = random.uniform(4.0, 6.0)
            self.unpredictability = 0.05
            self.repulsion_strength = repulsion_strength
        elif self.ped_profile == "Child":
            self.desired_speed = random.uniform(3.0, 8.0)
            self.unpredictability = 0.3
            self.repulsion_strength = repulsion_strength * 0.5
        elif self.ped_profile == "Elderly":
            self.desired_speed = random.uniform(2.0, 3.5)
            self.unpredictability = 0.02
            self.repulsion_strength = repulsion_strength * 1.5
        elif self.ped_profile == "Distracted":
            self.desired_speed = random.uniform(3.0, 5.0)
            self.unpredictability = 0.2
            self.repulsion_strength = repulsion_strength * 0.7
        self.velocity = self.desired_speed

class ObstructionActor(BaseActor):
    def __init__(self, model, geometry, crs, line_geom, spawn_dist, segment_id=None):
        super().__init__(model, geometry, crs, line_geom, spawn_dist, "Obstruction", "unknown", segment_id)
        self.velocity = 0

class MaKeNeSABM(mesa.Model):
    """
    Core Analytical Model utilizing mesa-geo, enhanced with kinematic physics.
    """
    def __init__(self, regional_network, topology=None, ptw_ratio=0.65, seed=None, sim_mode='rush_hour'):
        super().__init__()
        self.topology = topology # NetworkTopology instance
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        # Suppress massive GeoSpace CRS warning spam that slows down console I/O exponentially
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="mesa_geo")
        
        self.abm_actors = []
        self.regional_network = regional_network
        # self.schedule = mesa.time.RandomActivation(self)  # Deprecated in Mesa 3.0
        self.space = mg.GeoSpace(crs=self.regional_network.crs)
        
        self.segment_max_speeds = {}
        self.segment_curvatures = {}
        self.ptw_ratio = ptw_ratio
        self.sim_mode = sim_mode
        
        self.conflict_logs = []
        self.stress_events = [] # For the Human Experience index
        self.pet_logs = [] # Post-Encroachment Time
        self.frame_logs = [] # Trajectory logs for top-5 video replay
        
        self.segment_curvatures = {}
        self.step_count = 0
        self.sample_rate = 1
        
        self.segment_geometries = {}
        if self.regional_network is not None and not self.regional_network.empty:
            for idx, row in self.regional_network.iterrows():
                seg_id = int(row.get('OBJECTID', idx))
                self.segment_geometries[seg_id] = {
                    'geometry': row.geometry,
                    'RoadClass': row.get('RoadClass', 'secondary'),
                    'SpeedLimit': row.get('SpeedLimit', 50)
                }
                
        self.initialize_actors()

    def initialize_actors(self):
        if self.regional_network is None or self.regional_network.empty:
            return
            
        crs = self.regional_network.crs
        # User requested: Simulate all segments in the network
        spawn_network = self.regional_network
        
        for idx, row in spawn_network.iterrows():
            if row.geometry is None: continue
            
            import math
            def safe_float(val, fallback):
                try:
                    v = float(val)
                    return fallback if math.isnan(v) else v
                except (ValueError, TypeError):
                    return fallback
            
            speed_limit = safe_float(row.get('SpeedLimit', 50), 50)
            land_use = row.get('LandUse', 'UNKNOWN')
            road_class = row.get('RoadClass', 'UNKNOWN')
            
            # Phase 29: Use actual telemetry to spawn correct ratio of speeders
            median_speed = safe_float(row.get('MedianSpeed', speed_limit), speed_limit)
            f85_speed = safe_float(row.get('F85thPercentileSpeed', speed_limit), speed_limit)
            number_over_limit = int(safe_float(row.get('NumberOverLimit', 0), 0))
            
            seg_id = int(row.get('OBJECTID', idx))
            
            # --- Phase 35: Curvature Inference & Deep Context ---
            geom = row.geometry
            curvature_ratio = 1.0
            if geom and geom.geom_type in ['LineString', 'MultiLineString']:
                coords = list(geom.coords) if geom.geom_type == 'LineString' else list(geom.geoms[0].coords)
                if len(coords) >= 2:
                    straight_dist = Point(coords[0]).distance(Point(coords[-1]))
                    if straight_dist > 0:
                        curvature_ratio = max(1.0, geom.length / straight_dist)
            
            self.segment_curvatures[seg_id] = curvature_ratio
            
            # --- Contextual Zoning Inference & Mapillary Visual Friction Mock ---
            num_pedestrians = 0
            pedestrian_offset = 0.0001 # Default safe sidewalk distance
            visual_friction = 1.0 # 1.0 = normal, >1.0 = high friction (narrow roads, parked cars)
            
            # Phase 45: Nighttime & Low Visibility simulation
            is_night = random.random() < 0.3
            
            # Phase 46: Data-driven spawn ratios from enriched spatial columns
            # Use PopDensity_100m, POI counts, and OSM infrastructure to modulate spawns
            pop_density = safe_float(row.get('PopDensity_100m', 0), 0)
            schools_nearby = int(safe_float(row.get('POI_Schools_500m', 0), 0))
            hospitals_nearby = int(safe_float(row.get('POI_Hospitals_500m', 0), 0))
            transit_nearby = int(safe_float(row.get('POI_Transit_500m', 0), 0))
            markets_nearby = int(safe_float(row.get('POI_Markets_500m', 0), 0))
            cycleways_nearby = int(safe_float(row.get('OSM_Cycleways_500m', 0), 0))
            sidewalks_nearby = int(safe_float(row.get('OSM_Sidewalks_500m', 0), 0))
            crossings_nearby = int(safe_float(row.get('OSM_Crossings_500m', 0), 0)) + int(safe_float(row.get('Mapillary_Crosswalks', 0), 0))
            lighting_nearby = int(safe_float(row.get('OSM_StreetLighting_500m', 0), 0))
            bldg_density = safe_float(row.get('BuildingDensity_100m', 0), 0)
            traffic_calming = int(safe_float(row.get('OSM_TrafficCalming_500m', 0), 0))
            lane_count = int(safe_float(row.get('OSM_LaneCount', 1), 1))
            traffic_signs = int(safe_float(row.get('Mapillary_TrafficSigns', 0), 0))
            
            # Phase 35: Use UrbanPC directly if available
            urban_pc = safe_float(row.get('UrbanPC', 0), 0)
            # Data-driven pedestrian base: blend UrbanPC with population density
            # Pop density > 1000 = urban core, scale pedestrians accordingly
            pop_ped_boost = min(3, int(pop_density / 1500)) if pop_density > 0 else 0
            bldg_ped_boost = min(2, int(bldg_density / 15)) if bldg_density > 0 else 0
            poi_ped_boost = min(3, schools_nearby + hospitals_nearby + transit_nearby + markets_nearby)
            base_peds = min(5, int(urban_pc / 5)) if urban_pc > 0 else 1
            base_peds = max(base_peds, pop_ped_boost + bldg_ped_boost)
            
            if speed_limit <= 30 or (schools_nearby > 0 and speed_limit <= 50):
                # School / Hospital / High-Density Zone
                num_pedestrians = base_peds + random.randint(2, 4) + poi_ped_boost
                visual_friction = 1.5
            elif land_use == 'URBAN' and speed_limit <= 50:
                # Market / Mixed-Use
                num_pedestrians = base_peds + random.randint(2, 3) + min(2, poi_ped_boost)
                visual_friction = 1.3
            elif land_use == 'URBAN' and road_class in ['primary', 'trunk'] and speed_limit > 50:
                # Urban Arterial (Likely poor/missing sidewalks)
                num_pedestrians = max(1, base_peds // 2) + (1 if transit_nearby > 0 else 0)
                pedestrian_offset = 0.00002 # Extremely close to road centroid (fatal mismatch)
                visual_friction = 1.1
            elif land_use == 'RURAL' and road_class not in ['motorway'] and speed_limit < 80:
                # Rural Roads
                num_pedestrians = 1 if random.random() < 0.2 else 0
                visual_friction = 0.8
            elif road_class == 'motorway' or speed_limit >= 80:
                # Motorway / Expressway / Speedway (Very rare pedestrians, e.g. 0.2% chance)
                num_pedestrians = 1 if random.random() < 0.002 else 0
                visual_friction = 0.5
            else:
                # Fallback - use enrichment data if available
                num_pedestrians = max(1, pop_ped_boost)
                visual_friction = 1.0
                
            # Phase 35: Curvature heavily increases visual friction (blind corners)
            visual_friction *= min(1.2, curvature_ratio)
            
            # Phase 55: HeiGIT Road Surface & Smoothness impact on vehicles & visual friction
            surface_val = str(row.get('OSM_RoadSurface', '')).lower()
            smoothness_val = str(row.get('OSM_RoadSmoothness', '')).lower()
            is_unpaved_or_rough = (
                surface_val in ['unpaved', 'dirt', 'gravel', 'earth', 'sand', 'grass', 'mud'] or
                smoothness_val in ['bad', 'very_bad', 'rough', 'horrible', 'impassable', 'very_horrible']
            )
            if is_unpaved_or_rough:
                visual_friction *= 1.4
                median_speed *= 0.8
                f85_speed *= 0.8
            
            # Phase 46: Missing street lighting increases nighttime friction
            if is_night:
                if lighting_nearby == 0:
                    visual_friction *= 1.8  # No lighting = significantly worse
                else:
                    visual_friction *= 1.3  # Lighting present but still night
                
            # Phase 46: Missing sidewalks in urban areas increase friction
            if sidewalks_nearby == 0 and land_use == 'URBAN' and speed_limit <= 60:
                visual_friction *= 1.15
                pedestrian_offset *= 0.5  # Pedestrians closer to road without sidewalks
                
            # Apply visual friction to dynamic offsets (narrower visual friction brings VRUs closer to cars)
            pedestrian_offset = pedestrian_offset / visual_friction
                
            # Phase 29: Spawn Vehicles (Proportional to NumberOverLimit)
            # Base is 1 vehicle. Cap to 10 to prevent memory crash
            num_vehicles = 1
            
            seg_id = int(row.get('OBJECTID', idx))
            mobil_politeness = safe_float(row.get('mobil_politeness', 0.2), 0.2)
            sfm_rep = safe_float(row.get('sfm_repulsion_strength', 2.0), 2.0)
                
            # Phase 29: Spawn Vehicles dynamically based on typical vehicle volume (proportional scaling)
            # Use log10 scale to scale smoothly across wide ranges (thousands to millions)
            sample_size = safe_float(row.get('SampleSize_avg', 10), 10)
            log_vol = math.log10(max(10.0, sample_size))
            base_vol = log_vol * 4.0
            
            if number_over_limit > 0:
                base_vol += (number_over_limit / 20.0)
            
            # Phase 53: Lane Count Expansion
            base_vol *= lane_count
            
            if road_class == 'motorway' or speed_limit >= 80:
                base_vol = max(10.0, base_vol * 1.5) # Highways inherently have higher platooning
                
            # Phase 49: 24-Hour Day Rate Volume Proxy
            day_rate_multiplier = 3.0
            if getattr(self, 'sim_mode', 'rush_hour') == 'rush_hour':
                day_rate_multiplier = 7.5  # Boost vehicle volume by 2.5x for rush hour
                num_pedestrians = int(num_pedestrians * 2.0)
            
            # Populate with many actors: cap at 150 to keep simulation performing, floor at 10 for rich visual details
            num_vehicles = int(max(10, min(150, round(base_vol * day_rate_multiplier))))
            segment_length_deg = geom.length if geom else 100.0/111320.0
            
            # Phase 47: Inject opposing head-on traffic to trigger V2V conflicts
            for i in range(num_vehicles):
                # Phase 49: Distance-based geometric spawning uniformly across the road
                if self.topology and self.topology.is_one_way(seg_id):
                    direction = 1.0
                elif self.topology and self.topology.is_two_way(seg_id):
                    direction = 1.0 if random.random() < 0.5 else -1.0
                else:
                    direction = 1.0 if random.random() < 0.6 else -1.0
                spawn_dist = random.uniform(0.0, segment_length_deg)
                    
                if geom and geom.geom_type in ['LineString', 'MultiLineString']:
                    v_point = geom.interpolate(spawn_dist)
                else:
                    v_point = row.geometry.centroid
                
                o_lon, o_lat = v_point.x, v_point.y 
                
                # Phase 53: Traffic calming explicitly throttles speeds
                local_median_speed = median_speed * (0.85 if traffic_calming > 0 else 1.0)
                local_f85_speed = f85_speed * (0.85 if traffic_calming > 0 else 1.0)
                
                rand_val = random.random()
                agent_max_speed = local_f85_speed if random.random() < 0.2 else local_median_speed
                is_hgv_route = road_class in ['primary', 'trunk', 'motorway']
                
                if is_hgv_route and rand_val < 0.10:
                    v_actor = HGVActor(self, v_point, crs, agent_max_speed, geom, spawn_dist, road_class, seg_id, o_lon, o_lat, politeness=mobil_politeness, direction=direction)
                elif rand_val < (self.ptw_ratio + (0.10 if is_hgv_route else 0)):
                    v_actor = PTWActor(self, v_point, crs, agent_max_speed, geom, spawn_dist, road_class, seg_id, o_lon, o_lat, politeness=mobil_politeness, direction=direction)
                else:
                    v_actor = CarActor(self, v_point, crs, agent_max_speed, geom, spawn_dist, road_class, seg_id, o_lon, o_lat, politeness=mobil_politeness, direction=direction)
                    
                v_actor.is_night = is_night
                self.space.add_agents([v_actor])
                self.abm_actors.append(v_actor)
            
            # Calculate length for dynamic spawn rates
            length_factor = max(1, int((segment_length_deg * 111320.0) / 50.0))
            
            if num_pedestrians > 0:
                total_peds = int(min(5, num_pedestrians * length_factor))
                has_crosswalks = (visual_friction > 1.2) or (crossings_nearby > 0)
                
                for i in range(total_peds):
                    if has_crosswalks:
                        spawn_dist = 0.0 if random.random() < 0.5 else segment_length_deg
                    else:
                        spawn_dist = (i / max(1, total_peds)) * segment_length_deg
                        
                    if geom and geom.geom_type in ['LineString', 'MultiLineString']:
                        p_point = geom.interpolate(spawn_dist)
                    else:
                        p_point = row.geometry.centroid
                        
                    is_crossing = True if (random.random() < 0.4 or crossings_nearby > 0) else False
                    p_actor = PedestrianActor(self, p_point, crs, geom, spawn_dist, seg_id, p_point.x, p_point.y, sfm_rep, visual_friction, is_crossing)
                    self.space.add_agents([p_actor])
                    self.abm_actors.append(p_actor)

            # Phase 46: Data-driven cyclist spawning using OSM cycleway data
            num_cyclists = 0
            if road_class != 'motorway' and speed_limit <= 60:
                # Base cyclist probability from enrichment data
                if cycleways_nearby > 0:
                    # Dedicated cycleways attract more cyclists
                    num_cyclists = min(3, cycleways_nearby) if random.random() < 0.6 else 1
                elif land_use == 'URBAN':
                    num_cyclists = 1 if random.random() < 0.35 else 0
                    if speed_limit <= 40:
                        num_cyclists += 1 if random.random() < 0.25 else 0
            num_cyclists = min(num_cyclists, 3)
            for i in range(num_cyclists):
                spawn_dist = ((i + 0.5) / max(1, num_cyclists)) * segment_length_deg
                if geom and geom.geom_type in ['LineString', 'MultiLineString']:
                    c_point = geom.interpolate(spawn_dist)
                else:
                    c_point = row.geometry.centroid
                c_direction = 1.0 if random.random() < 0.5 else -1.0
                c_actor = CyclistActor(self, c_point, crs, geom, spawn_dist, seg_id, c_point.x, c_point.y, direction=c_direction)
                self.space.add_agents([c_actor])
                self.abm_actors.append(c_actor)
                    
            num_obstructions = 1 # Force at least 1 obstruction for testing V2O
            if visual_friction > 1.2:
                num_obstructions += random.randint(1, 2)
                
            # Phase 49: Obstructions tied heavily to corners/curves (apex spawning)
            if curvature_ratio > 1.1:
                num_curve_obs = random.randint(1, 3)
                for _ in range(num_curve_obs):
                    # Spawn near the middle where the apex of the curve likely is
                    spawn_dist = (segment_length_deg / 2.0) + random.uniform(-10.0/111320.0, 10.0/111320.0)
                    spawn_dist = max(0.0, min(spawn_dist, segment_length_deg))
                    if geom and geom.geom_type in ['LineString', 'MultiLineString']:
                        o_point = geom.interpolate(spawn_dist)
                    else:
                        o_point = row.geometry.centroid
                    obs_actor = ObstructionActor(self, o_point, crs, geom, spawn_dist, seg_id)
                    self.space.add_agents([obs_actor])
                    self.abm_actors.append(obs_actor)
                
            if bldg_density > 20:
                num_obstructions += min(4, int(bldg_density / 15.0))
                
            if road_class == 'motorway' or speed_limit >= 80:
                num_obstructions = (1 if random.random() < 0.10 else 0)
                
            for _ in range(num_obstructions):
                spawn_dist = random.uniform(0, segment_length_deg)
                if geom and geom.geom_type in ['LineString', 'MultiLineString']:
                    o_point = geom.interpolate(spawn_dist)
                else:
                    o_point = row.geometry.centroid
                    
                obs_actor = ObstructionActor(self, o_point, crs, geom, spawn_dist, seg_id)
                self.space.add_agents([obs_actor])
                self.abm_actors.append(obs_actor)

    def calculate_ttc(self, actor_a, actor_b):
        dist_m = math.hypot((actor_b.geometry.x - actor_a.geometry.x) * 111320.0, (actor_b.geometry.y - actor_a.geometry.y) * 111320.0)
        
        v_a = actor_a.velocity / 3.6
        v_b = actor_b.velocity / 3.6
        stationary = ['Obstruction', 'Pedestrian']
        if getattr(actor_a, 'actor_type', '') in stationary: v_a = 0
        if getattr(actor_b, 'actor_type', '') in stationary: v_b = 0
        
        if hasattr(actor_a, 'distance_traveled') and hasattr(actor_b, 'distance_traveled'):
            dir_a = getattr(actor_a, 'base_direction', 1.0)
            dir_b = getattr(actor_b, 'base_direction', 1.0)
            
            # For stationary objects, assume they don't have a specific direction opposing traffic unless set
            if v_a == 0: dir_a = 0
            if v_b == 0: dir_b = 0
            
            v_a_dir = v_a * dir_a
            v_b_dir = v_b * dir_b
            
            # Phase 42 Continuity Fix: 
            # If actors have a high lateral offset difference (e.g. car in lane vs pedestrian on sidewalk)
            # they are not in the direct physical path. We must filter these to prevent false TTC alarms.
            lat_a = getattr(actor_a, 'lateral_offset', 0.0)
            lat_b = getattr(actor_b, 'lateral_offset', 0.0)
            # Convert degrees to meters for lateral check
            lat_diff_m = abs(lat_a - lat_b) * 111320.0
            
            if lat_diff_m > 2.5:
                # Laterally safe (e.g., pedestrian walking ALONG the sidewalk, not crossing)
                return float('inf')
            
            if actor_a.distance_traveled < actor_b.distance_traveled:
                rel_v = v_a_dir - v_b_dir
            else:
                rel_v = v_b_dir - v_a_dir
                
            if rel_v > 0:
                return dist_m / rel_v
                
        return float('inf')

    def apply_psychological_repulsion(self, vehicle, pedestrian):
        """
        Implements the psychological repulsion force from research3.md.
        If a pedestrian is close, the vehicle must decelerate.
        """
        dist_m = math.hypot((pedestrian.geometry.x - vehicle.geometry.x) * 111320.0, (pedestrian.geometry.y - vehicle.geometry.y) * 111320.0)
        if dist_m < 50.0: # 50 meters
            # Apply severe deceleration
            repulsion_strength = getattr(pedestrian, 'repulsion_strength', 2.0)
            repulsion_force = - (repulsion_strength / max(dist_m, 1.0))
            vehicle.acceleration = min(vehicle.acceleration, repulsion_force)
            
            # Log extreme stress events for the Human Experience Score
            if vehicle.acceleration < -3.0:
                self.stress_events.append({
                    'vehicle_type': vehicle.actor_type,
                    'location': [vehicle.orig_lon, vehicle.orig_lat],
                    'deceleration': vehicle.acceleration,
                    'segment_id': vehicle.segment_id
                })

    def _near_junction(self, actor, node):
        dist_m = math.hypot((actor.geometry.x - node[0]) * 111320.0, (actor.geometry.y - node[1]) * 111320.0)
        return dist_m < 30.0 # within 30 meters of the junction node

    def step(self):
        # 1. Pre-compute interactions
        # Group actors by segment_id for ultra-fast localized lookup
        segment_map = {}
        for a in self.abm_actors:
            sid = getattr(a, 'segment_id', None)
            if sid not in segment_map: segment_map[sid] = []
            segment_map[sid].append(a)

        vehicles = [a for a in self.abm_actors if a.actor_type in ["Car", "PTW", "HGV"]]
        pedestrians = [a for a in self.abm_actors if a.actor_type == "Pedestrian"]
        cyclists = [a for a in self.abm_actors if a.actor_type == "Cyclist"]
        vru_actors = pedestrians + cyclists
        
        for v in vehicles:
            # Distance in degrees (~35 meters)
            # Optimize: Agents wrap around their own segment, so they only interact with actors on the same segment
            segment_actors = segment_map.get(getattr(v, 'segment_id', None), [])
            
            # Fast filter by distance (L1 norm heuristic to avoid hypot for far actors)
            threshold = 35.0 / 111320.0
            nearby_actors = []
            for a in segment_actors:
                if a == v: continue
                # Quick bounding box check
                if abs(a.geometry.x - v.geometry.x) < threshold and abs(a.geometry.y - v.geometry.y) < threshold:
                    nearby_actors.append(a)
                    
            # Prevent O(N^2) memory/cpu explosion in heavy congestion:
            # Cap the physical simulation to the immediate 15 surrounding actors.
            if len(nearby_actors) > 15:
                nearby_actors = random.sample(nearby_actors, 15)
            
            # --- Safety in Numbers (SiN) ---
            nearby_vru = [a for a in nearby_actors if a.actor_type in ("Pedestrian", "Cyclist")]
            if len(nearby_vru) > 3:
                # Drop desired speed due to high VRU density
                v.desired_speed = max(20.0, v.max_speed * (0.9 ** len(nearby_vru)))
            else:
                v.desired_speed = v.max_speed
            
            # --- V2V Collision Checking (IDM interaction term & 2D Vector) ---
            nearby_vehicles = [a for a in nearby_actors if a.actor_type in ["Car", "PTW", "HGV"] and a != v]
            for other_v in nearby_vehicles:
                ttc = self.calculate_ttc(v, other_v)
                dist_m = math.hypot((other_v.geometry.x - v.geometry.x) * 111320.0, (other_v.geometry.y - v.geometry.y) * 111320.0)
                
                # V2V Conflict Log
                if ttc < 8.0 and dist_m < 100.0:
                    self.conflict_logs.append({
                        'type': 'V2V',
                        'vehicle_id': v.unique_id,
                        'target_id': other_v.unique_id,
                        'ttc': ttc,
                        'location': [v.orig_lon, v.orig_lat],
                        'segment_id': v.segment_id
                    })
                    
                # 1D IDM Interaction if in same direction
                if getattr(v, 'base_direction', 1.0) == getattr(other_v, 'base_direction', 1.0):
                    is_ahead = (v.base_direction == 1.0 and other_v.distance_traveled > v.distance_traveled) or (v.base_direction == -1.0 and other_v.distance_traveled < v.distance_traveled)
                    if dist_m > 0 and is_ahead:
                        delta_v = (v.velocity - other_v.velocity) / 3.6
                        if delta_v > 0:
                            s_star = v.min_gap + (v.velocity/3.6)*v.safe_time_headway + ((v.velocity/3.6)*delta_v)/(2*np.sqrt(v.max_acceleration*v.desired_deceleration))
                            idm_interaction = -v.max_acceleration * ((s_star / dist_m) ** 2)
                            v.acceleration += idm_interaction # Will decrease velocity in step()
                else:
                    # Cross or Opposing traffic: severe deceleration if TTC is low
                    if ttc < 3.0:
                        v.acceleration -= v.desired_deceleration
            
            # --- Vehicle to VRU Interaction (pedestrians & cyclists) ---
            for p in nearby_vru:
                ttc = self.calculate_ttc(v, p)
                if ttc < 3.0:
                    self.conflict_logs.append({
                        'type': 'VRU',
                        'vru_class': p.actor_type,
                        'vehicle_id': v.unique_id,
                        'vru_id': p.unique_id,
                        'ttc': ttc,
                        'location': [v.orig_lon, v.orig_lat],
                        'segment_id': v.segment_id
                    })
                
                # Post-Encroachment Time (PET) tracking proxy for VRUs
                dist_m = math.hypot((p.geometry.x - v.geometry.x) * 111320.0, (p.geometry.y - v.geometry.y) * 111320.0)
                if dist_m < 10.0 and ttc > 0 and ttc < 3.0:
                    pet = ttc + (dist_m / max(0.1, (v.velocity/3.6)))
                    if pet < 3.0:
                        self.pet_logs.append({
                            'vehicle_id': v.unique_id,
                            'vru_id': p.unique_id,
                            'pet': pet,
                            'location': [v.orig_lon, v.orig_lat],
                            'segment_id': v.segment_id
                        })
                
                # Apply human comfort/stress rules
                self.apply_psychological_repulsion(v, p)
                    
            # --- V2O Interaction (Obstructions & Curvature Run-Off Risk) ---
            curvature = self.segment_curvatures.get(v.segment_id, 1.0)
            if curvature > 1.01:
                v_m_s = v.velocity / 3.6
                mass_factor = 5.0 if v.actor_type == "HGV" else (1.5 if v.actor_type == "Car" else 0.8)
                # Momentum-based centrifugal risk: mass * v^2 * (curvature - 1.0)
                momentum_risk = mass_factor * (v_m_s ** 2) * (curvature - 1.0)
                if momentum_risk > 120.0:
                    # Log a V2O conflict due to centrifugal run-off-road risk on curves
                    self.conflict_logs.append({
                        'type': 'V2O',
                        'vehicle_id': v.unique_id,
                        'target_id': f"Curve_{v.segment_id}",
                        'ttc': max(0.5, min(8.0, 15.0 / max(0.1, v_m_s))),
                        'location': [v.orig_lon, v.orig_lat],
                        'segment_id': v.segment_id
                    })
                    
            nearby_obstructions = [a for a in nearby_actors if a.actor_type == "Obstruction"]
            for o in nearby_obstructions:
                dist_m = math.hypot((o.geometry.x - v.geometry.x) * 111320.0, (o.geometry.y - v.geometry.y) * 111320.0)
                is_ahead = (getattr(v, 'base_direction', 1.0) == 1.0 and o.distance_traveled > v.distance_traveled) or (getattr(v, 'base_direction', 1.0) == -1.0 and o.distance_traveled < v.distance_traveled)
                
                if is_ahead and dist_m < 100.0 and v.velocity > 30.0:
                    # Treat like a stationary collision vector
                    ttc = dist_m / max(0.1, (v.velocity / 3.6))
                    if ttc < 8.0:
                        self.conflict_logs.append({
                            'type': 'V2O',
                            'vehicle_id': v.unique_id,
                            'target_id': o.unique_id,
                            'ttc': ttc,
                            'location': [v.orig_lon, v.orig_lat],
                            'segment_id': v.segment_id
                        })
                
        # 2. Execute movement
        random.shuffle(self.abm_actors)
        for actor in self.abm_actors:
            actor.step()
            
        # Clean up despawned actors
        self.abm_actors = [a for a in self.abm_actors if not getattr(a, 'despawn', False)]
            
        # Junction Conflict Checking (degree >= 3 intersections)
        if self.topology:
            post_move_segment_map = {}
            for a in self.abm_actors:
                sid = getattr(a, 'segment_id', None)
                if sid not in post_move_segment_map: post_move_segment_map[sid] = []
                post_move_segment_map[sid].append(a)
                
            for node, segments in self.topology.junction_segments.items():
                if len(segments) < 3:
                    continue
                junction_actors = []
                for sid in segments:
                    if sid in self.segment_geometries:
                        junction_actors.extend([
                            a for a in post_move_segment_map.get(sid, [])
                            if a.actor_type in ['Car', 'PTW', 'HGV'] and self._near_junction(a, node)
                        ])
                for i, a in enumerate(junction_actors):
                    for b in junction_actors[i+1:]:
                        if a.segment_id == b.segment_id:
                            continue
                        ttc = self.calculate_ttc(a, b)
                        if ttc < 5.0:
                            self.conflict_logs.append({
                                'type': 'JUNCTION',
                                'vehicle_id': a.unique_id,
                                'target_id': b.unique_id,
                                'ttc': ttc,
                                'location': [node[0], node[1]],
                                'segment_id': a.segment_id
                            })
            
        # 3. Record trajectory frame for playable video (up to 1500 frames, sampled)
        self.step_count = getattr(self, 'step_count', 0) + 1
        sample_rate = getattr(self, 'sample_rate', 1)
        if self.step_count % sample_rate == 0:
            if len(self.frame_logs) < 1500:
                current_frame = []
                for a in self.abm_actors:
                    sid = getattr(a, 'segment_id', None)
                    # OOM Protection: Only save frames for actors on top-priority roads (we can't store 69k roads in memory)
                    if sid is not None and getattr(self, 'video_sids', None) and sid not in self.video_sids:
                        continue
                    current_frame.append({
                        'id': a.unique_id,
                        'type': a.actor_type,
                        'x': a.geometry.x,
                        'y': a.geometry.y,
                        'segment_id': sid,
                        'heading': math.atan2(getattr(a, 'heading_y', 0.0), getattr(a, 'heading_x', 1.0))
                    })
                self.frame_logs.append(current_frame)

    def steer_simulation(self):
        """
        Phase 17 Hook: Mid-simulation evaluation. 
        Uses a heuristic fallback instead of full LLM latency.
        """
        # Calculate intermediate PET hazard rate
        pet_count = len(self.pet_logs)
        if pet_count > 10:
            print(f"[WARNING] [Mid-Sim Steering Hook]: High VRU PET Hazards detected ({pet_count}). Applying behavioral traffic calming...")
            vehicles = [a for a in self.abm_actors if a.actor_type in ["Car", "PTW", "HGV"]]
            for v in vehicles:
                # Behaviorally reduce desired speeds across the board
                v.max_speed *= 0.85
                v.desired_speed = min(v.desired_speed, v.max_speed)
                # Increase safe time headway to force passive driving
                v.safe_time_headway *= 1.5
                
            pedestrians = [a for a in self.abm_actors if a.actor_type == "Pedestrian"]
            for p in pedestrians:
                # Increase psychological repulsion as pedestrians become hyper-aware
                p.repulsion_strength *= 1.2

    def run_simulation(self, steps=300, region_id="unknown"):
        self.sample_rate = max(1, steps // 300)
        midpoint = steps // 2
        import time
        start_time = time.time()
        print(f"[{region_id}] Starting simulation with {len(self.abm_actors)} actors...")
        for step_num in range(steps):
            if step_num % 10 == 0:
                print(f"[{region_id}] Step {step_num}/{steps} (Time elapsed: {time.time()-start_time:.2f}s)")
            self.step()
            
            if step_num == midpoint:
                self.steer_simulation()
                
        print(f"Simulation complete ({steps} steps). Detected {len(self.conflict_logs)} critical conflicts (TTC < 3.0s), {len(self.pet_logs)} PET hazards, and {len(self.stress_events)} high-stress events.")
        
        # Save synthetic data logs (overwrites previous state to avoid duplication)
        self.save_synthetic_actor_experience(region_id)
        
        return self.conflict_logs, self.pet_logs, self.stress_events, self.frame_logs
        
    def save_synthetic_actor_experience(self, region_id):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        synth_dir = os.path.join(base_dir, 'data', 'synthetic')
        os.makedirs(synth_dir, exist_ok=True)
        
        export_data = {
            'region_id': region_id,
            'conflicts': self.conflict_logs,
            'pet_hazards': self.pet_logs,
            'stress_events': self.stress_events
        }
        
        out_path = os.path.join(synth_dir, f"{region_id}_actor_experience.json")
        with open(out_path, 'w') as f:
            json.dump(export_data, f, indent=4)
        print(f"Saved synthetic actor experience logs to {out_path}")
