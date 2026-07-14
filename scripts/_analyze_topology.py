"""
Analyze network topology: build adjacency graph from shared endpoints,
determine one-way vs two-way from segment pairs, and check intersection degrees.
"""
import geopandas as gpd
from collections import defaultdict
import numpy as np

print("Loading network...")
gdf = gpd.read_file("makenes_scored.geojson")
print(f"Total segments: {len(gdf)}")

# Build node index: map rounded (lon, lat) -> list of (segment_idx, is_start)
PRECISION = 5  # ~1.1m precision
node_index = defaultdict(list)

for idx, row in gdf.iterrows():
    g = row.geometry
    if g is None or g.geom_type != 'LineString':
        continue
    coords = list(g.coords)
    start = (round(coords[0][0], PRECISION), round(coords[0][1], PRECISION))
    end = (round(coords[-1][0], PRECISION), round(coords[-1][1], PRECISION))
    oid = int(row.get('OBJECTID', idx))
    node_index[start].append((oid, 'start'))
    node_index[end].append((oid, 'end'))

# Count junction degrees
junction_degrees = {k: len(v) for k, v in node_index.items()}
degree_counts = defaultdict(int)
for d in junction_degrees.values():
    degree_counts[d] += 1

print(f"\nTotal unique nodes: {len(node_index)}")
print(f"Node degree distribution:")
for d in sorted(degree_counts.keys()):
    print(f"  Degree {d}: {degree_counts[d]} nodes")

# Identify intersections (degree >= 3)
intersections = {k: v for k, v in node_index.items() if len(v) >= 3}
print(f"\nIntersections (degree >= 3): {len(intersections)}")

# Detect paired segments (same start/end but reversed = two-way road)
# A pair is: segment A has start=X, end=Y; segment B has start=Y, end=X
segment_endpoints = {}
for idx, row in gdf.iterrows():
    g = row.geometry
    if g is None or g.geom_type != 'LineString':
        continue
    coords = list(g.coords)
    start = (round(coords[0][0], PRECISION), round(coords[0][1], PRECISION))
    end = (round(coords[-1][0], PRECISION), round(coords[-1][1], PRECISION))
    oid = int(row.get('OBJECTID', idx))
    segment_endpoints[oid] = (start, end)

# Find reverse pairs
reverse_pairs = 0
one_way_candidates = 0
paired_set = set()
for oid, (s, e) in segment_endpoints.items():
    if oid in paired_set:
        continue
    # Look for a segment with start=e, end=s
    for other_oid, (os, oe) in segment_endpoints.items():
        if other_oid != oid and other_oid not in paired_set:
            if os == e and oe == s:
                reverse_pairs += 1
                paired_set.add(oid)
                paired_set.add(other_oid)
                break

unpaired = len(segment_endpoints) - len(paired_set)
print(f"\nReverse pairs detected (two-way roads): {reverse_pairs}")
print(f"Segments in pairs: {len(paired_set)}")
print(f"Unpaired segments (potential one-way or dead-end): {unpaired}")

# Build adjacency: for each segment, find all segments sharing a node
adjacency = defaultdict(set)
for node, segment_list in node_index.items():
    oids = [s[0] for s in segment_list]
    for i in range(len(oids)):
        for j in range(i+1, len(oids)):
            adjacency[oids[i]].add(oids[j])
            adjacency[oids[j]].add(oids[i])

neighbor_counts = [len(v) for v in adjacency.values()]
print(f"\nSegments with at least 1 neighbor: {len(adjacency)}")
print(f"Isolated segments (no shared nodes): {len(gdf) - len(adjacency)}")
if neighbor_counts:
    print(f"Avg neighbors per segment: {np.mean(neighbor_counts):.1f}")
    print(f"Max neighbors: {max(neighbor_counts)}")
    print(f"Median neighbors: {np.median(neighbor_counts):.0f}")

# Sample a 5-segment neighborhood
sample_oid = list(adjacency.keys())[0]
sample_neighbors = adjacency[sample_oid]
print(f"\nSample: Segment {sample_oid} has {len(sample_neighbors)} neighbors: {list(sample_neighbors)[:10]}")
