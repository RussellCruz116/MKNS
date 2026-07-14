import geopandas as gpd
from collections import defaultdict
from shapely.geometry import Point

class NetworkTopology:
    """
    Builds a segment adjacency graph from shared LineString endpoints.
    Infers flow direction (one-way vs two-way) from reverse-pair detection.
    Provides junction metadata (degree, intersection type).
    """
    
    def __init__(self, gdf, precision=5):
        self.gdf = gdf
        self.precision = precision  # ~1.1m snapping precision (5 decimal places)
        
        # Core data structures
        self.node_index = defaultdict(list)          # (lon,lat) -> [(oid, 'start'|'end'), ...]
        self.adjacency = defaultdict(set)            # oid -> set(neighbor_oids)
        self.segment_nodes = {}                      # oid -> (start_node, end_node)
        self.reverse_pairs = {}                      # oid -> paired_oid (bidirectional)
        self.junction_degree = {}                    # (lon,lat) -> int
        self.junction_segments = defaultdict(set)    # (lon,lat) -> set(oids)
        self.is_one_way_flag = {}                    # oid -> bool
        
        self._build()
        
    def _build(self):
        # Phase 1: Index all segment endpoints
        for idx, row in self.gdf.iterrows():
            g = row.geometry
            if g is None:
                continue
                
            if g.geom_type == 'LineString':
                coords = list(g.coords)
            elif g.geom_type == 'MultiLineString':
                coords = []
                for line in g.geoms:
                    coords.extend(list(line.coords))
            else:
                continue
                
            if len(coords) < 2:
                continue
                
            start = (round(coords[0][0], self.precision), round(coords[0][1], self.precision))
            end = (round(coords[-1][0], self.precision), round(coords[-1][1], self.precision))
            oid = int(row.get('OBJECTID', idx))
            
            self.segment_nodes[oid] = (start, end)
            self.node_index[start].append((oid, 'start'))
            self.node_index[end].append((oid, 'end'))
            self.junction_segments[start].add(oid)
            self.junction_segments[end].add(oid)
            
        # Phase 2: Build adjacency from shared nodes
        for node, segment_list in self.node_index.items():
            self.junction_degree[node] = len(segment_list)
            oids = [s[0] for s in segment_list]
            for i in range(len(oids)):
                for j in range(i+1, len(oids)):
                    self.adjacency[oids[i]].add(oids[j])
                    self.adjacency[oids[j]].add(oids[i])
                    
        # Phase 3: Detect reverse pairs via endpoint-swap matching
        endpoint_map = {}
        for oid, (s, e) in self.segment_nodes.items():
            endpoint_map[(s, e)] = oid
            
        for oid, (s, e) in self.segment_nodes.items():
            reverse_key = (e, s)
            if reverse_key in endpoint_map:
                partner = endpoint_map[reverse_key]
                if partner != oid:
                    self.reverse_pairs[oid] = partner
                    self.reverse_pairs[partner] = oid
                    
        # Phase 4: Infer one-way: segments without a reverse pair are one-way
        for oid in self.segment_nodes.keys():
            self.is_one_way_flag[oid] = (oid not in self.reverse_pairs)
            
        self.gdf = None
            
    def get_neighbors(self, oid):
        """Returns set of segment OIDs connected to this segment."""
        return self.adjacency.get(oid, set())
        
    def is_one_way(self, oid):
        """True if this segment is inferred as one-way."""
        return self.is_one_way_flag.get(oid, True)
        
    def is_two_way(self, oid):
        """True if this segment has a reverse-direction counterpart."""
        return oid in self.reverse_pairs
        
    def get_reverse_pair(self, oid):
        """Returns the OBJECTID of the reverse-direction segment, or None."""
        return self.reverse_pairs.get(oid, None)
        
    def get_downstream_for_node(self, node, coming_from_oid):
        """
        Returns all segments connected to `node` that can be entered from `coming_from_oid`.
        For one-way roads, they can only be entered if they start at `node`.
        For two-way roads, they can be entered in either direction.
        """
        downstream = set()
        for other_oid, role in self.node_index.get(node, []):
            if other_oid == coming_from_oid:
                continue
            if self.is_one_way(other_oid):
                if role == 'start':
                    downstream.add(other_oid)
            else:
                downstream.add(other_oid)
        return downstream

    def get_downstream_segments(self, oid):
        """Helper to get downstream segments at the end of the digitized direction."""
        nodes = self.segment_nodes.get(oid)
        if not nodes:
            return set()
        return self.get_downstream_for_node(nodes[1], oid)

    def get_upstream_segments(self, oid):
        """Helper to get upstream segments feeding into the start of the digitized direction."""
        nodes = self.segment_nodes.get(oid)
        if not nodes:
            return set()
        upstream = set()
        for other_oid, role in self.node_index.get(nodes[0], []):
            if other_oid == oid:
                continue
            if self.is_one_way(other_oid):
                if role == 'end':
                    upstream.add(other_oid)
            else:
                upstream.add(other_oid)
        return upstream
