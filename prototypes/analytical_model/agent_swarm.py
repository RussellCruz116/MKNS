import os
import geopandas as gpd
from sklearn.cluster import KMeans
import numpy as np

class AgentSwarm:
    """
    Dynamically partitions a massive regional network into spatial clusters using K-Means.
    Assigns each cluster to a specialized 'Sub-Supervisor' based on the road density of that cluster.
    """
    def __init__(self, main_supervisor, network_gdf: gpd.GeoDataFrame):
        self.main_supervisor = main_supervisor
        self.network = network_gdf.copy()
        
    def spawn_sub_supervisors(self):
        """
        Clusters the network and returns a list of (sub_supervisor_id, sub_network_gdf, context)
        """
        print(f"[{self.main_supervisor.name}] Analyzing Network Topology for Sub-Supervisor Swarm Deployment...")
        
        # Calculate dynamic K based on network size. 
        # User requested deep subclustering. 1 sub-supervisor per 2,000 segments.
        total_segments = len(self.network)
        k_clusters = max(5, total_segments // 2000) # Minimum 5, highly granular.
        
        print(f"[{self.main_supervisor.name}] Network size: {total_segments}. Spawning {k_clusters} Sub-Supervisors.")
        
        # Extract centroids for clustering
        centroids = self.network.geometry.centroid
        coords = np.column_stack((centroids.x, centroids.y))
        
        # Run K-Means Clustering
        kmeans = KMeans(n_clusters=k_clusters, random_state=42, n_init=10)
        self.network['ClusterID'] = kmeans.fit_predict(coords)
        
        sub_regions = []
        
        for cluster_id in range(k_clusters):
            cluster_gdf = self.network[self.network['ClusterID'] == cluster_id].copy()
            
            # Determine density: (Number of segments) / (Area of bounding box)
            # Area is rough since we are in EPSG:4326, but it works as a relative proxy.
            bounds = cluster_gdf.total_bounds
            area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
            density = len(cluster_gdf) / (area + 1e-9)
            
            # Assign Context Persona
            if density > 50000: # Arbitrary high density threshold for relative comparison
                context = "urban_subsupervisor.md"
                label = "Urban"
            else:
                context = "rural_subsupervisor.md"
                label = "Rural"
                
            print(f"  -> Spawned Sub-Supervisor {cluster_id} ({label}) | Segments: {len(cluster_gdf)} | Density proxy: {density:.1f}")
            
            sub_regions.append({
                'cluster_id': cluster_id,
                'gdf': cluster_gdf,
                'persona_file': context,
                'label': label
            })
            
        return sub_regions
