import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans

class ArchetypeDiscovery:
    """
    Unsupervised Learning Module to discover Latent Safety Archetypes from 
    highly dimensional kinematic, geometric, and telemetry data.
    """
    def __init__(self, network_df, n_clusters=12):
        # We work on a copy to ensure we don't mutate the raw data unintentionally
        self.raw_df = network_df.copy()
        self.n_clusters = n_clusters
        
        # Define the numerical features that dictate "Safety Physics"
        self.feature_columns = [
            'SpeedLimit',
            'F85thPercentileSpeed',
            'MedianSpeed',
            'UrbanPC',
            'SegmentLength',
            'EffectiveHazards_VRU',
            'SegmentConflicts_V2V',
            'SegmentConflicts_V2O',
            'Score_Kinematics',
            'Score_VRU',
            'SpeedSafetyScore'
        ]

    def discover_archetypes(self):
        print(f"[Archetype Discovery] Initializing Unsupervised Learning on {len(self.raw_df)} segments...")
        
        # 1. Isolate and Clean Features
        # Ensure all required columns exist; fill missing with 0 for PCA
        features = pd.DataFrame(index=self.raw_df.index)
        for col in self.feature_columns:
            if col in self.raw_df.columns:
                features[col] = pd.to_numeric(self.raw_df[col], errors='coerce').fillna(0)
            else:
                features[col] = 0.0
                
        # 2. Standardization
        scaler = StandardScaler()
        scaled_features = scaler.fit_transform(features)
        
        # 3. Principal Component Analysis (PCA)
        # Reduce to components that explain 95% of the variance
        pca = PCA(n_components=0.95, random_state=42)
        principal_components = pca.fit_transform(scaled_features)
        n_components_used = pca.n_components_
        print(f"[Archetype Discovery] PCA compressed {len(self.feature_columns)} dimensions into {n_components_used} Principal Components.")
        
        # 4. K-Means Clustering
        kmeans = KMeans(n_clusters=self.n_clusters, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(principal_components)
        
        # Attach the discovered archetype labels back to the ORIGINAL raw dataframe
        # This explicitly fulfills the requirement: "ensure that the values in the raw dataset are not loss"
        self.raw_df['LatentArchetypeID'] = cluster_labels
        
        # 5. Extract Cluster Centroids (Mean characteristics of each archetype)
        # This is what the LLM will analyze
        cluster_summaries = {}
        for cluster_id in range(self.n_clusters):
            cluster_subset = self.raw_df[self.raw_df['LatentArchetypeID'] == cluster_id]
            
            summary = {
                'ClusterSize': len(cluster_subset),
                'SpeedLimit': cluster_subset['SpeedLimit'].mean() if 'SpeedLimit' in cluster_subset else 50,
                'F85': cluster_subset['F85thPercentileSpeed'].mean() if 'F85thPercentileSpeed' in cluster_subset else 50,
                'S3_Avg': cluster_subset['SpeedSafetyScore'].mean() if 'SpeedSafetyScore' in cluster_subset else 100,
                'Avg_EffectiveHazards': cluster_subset['EffectiveHazards_VRU'].mean() if 'EffectiveHazards_VRU' in cluster_subset else 0,
                'Avg_V2V_Conflicts': cluster_subset['SegmentConflicts_V2V'].mean() if 'SegmentConflicts_V2V' in cluster_subset else 0,
                'Avg_V2O_Conflicts': cluster_subset['SegmentConflicts_V2O'].mean() if 'SegmentConflicts_V2O' in cluster_subset else 0,
                'Score_Kinematics': cluster_subset['Score_Kinematics'].mean() if 'Score_Kinematics' in cluster_subset else 30,
                'Max_Kinematics': 30, # Assuming max is 30 for the prompt context
                'Score_VRU': cluster_subset['Score_VRU'].mean() if 'Score_VRU' in cluster_subset else 15,
                'Max_VRU': 15,
            }
            cluster_summaries[f"PCA_Cluster_{cluster_id}"] = summary
            
        print(f"[Archetype Discovery] Successfully discovered {self.n_clusters} Latent Archetypes.")
        
        return self.raw_df, cluster_summaries
