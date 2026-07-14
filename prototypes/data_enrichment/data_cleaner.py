import pandas as pd
import geopandas as gpd
import numpy as np

class DataCleaner:
    """
    Cleans and imputes missing values in the network dataset before ABM and scoring.
    Uses spatial topology and k-nearest neighbors to impute continuous metrics,
    avoiding the false assumption that missing data equals zero.
    """
    def __init__(self, country=None):
        self.country = country

    def clean(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        print("[DataCleaner] Starting intelligent data imputation...")
        
        # Define the columns that need imputation
        num_cols = [
            'F85thPercentileSpeed', 'MedianSpeed', 'PercentOverLimit', 
            'RankedPercentile', 'SampleSize_avg', 'WeightedSample', 
            'MapillaryVisualFriction', 'PopDensity_100m', 'BuildingDensity_100m',
            'UrbanCentre_Pop', 'POI_Schools_500m', 'POI_Hospitals_500m',
            'POI_Transit_500m', 'POI_Markets_500m', 'OSM_Sidewalks_500m',
            'OSM_Crossings_500m', 'OSM_TrafficCalming_500m', 'OSM_StreetLighting_500m',
            'OSM_Cycleways_500m', 'Mapillary_TrafficSigns', 'Mapillary_Crosswalks'
        ]
        cat_cols = ['LandUse', 'RoadClass']
        
        # Ensure num_cols exist and are numeric
        for col in num_cols:
            if col in gdf.columns:
                gdf[col] = pd.to_numeric(gdf[col], errors='coerce')
        
        def is_cat_nan(val):
            return pd.isna(val) or val in ['UNKNOWN', 'unknown', 'Unknown', '', None]

        num_with_nans = [c for c in num_cols if c in gdf.columns]
        cat_with_nans = [c for c in cat_cols if c in gdf.columns]
        
        imputed_tracker = {idx: [] for idx in gdf.index}
        
        # 1. Neighbor-based Imputation (Topological / Spatial)
        has_nan = gdf[num_with_nans].isna().any(axis=1)
        for cat in cat_with_nans:
            has_nan = has_nan | gdf[cat].apply(is_cat_nan)
            
        nan_indices = gdf[has_nan].index
        
        if len(nan_indices) > 0:
            print(f"    [DataCleaner] Imputing missing values for {len(nan_indices)} segments using spatial neighbors...")
            # We use sindex for faster topological queries
            if not gdf.sindex:
                print("    [DataCleaner] Generating spatial index...")
            sindex = gdf.sindex
            
            for idx in nan_indices:
                geom = gdf.at[idx, 'geometry']
                if geom is None:
                    continue
                    
                # Find up to 3 nearest neighbors quickly
                # This returns (array of geometry indices of gdf, array of geometry indices of neighbors)
                # We can just use sindex.nearest(geom, return_all=False, max_distance=100/111320.0)
                # But since it's an apply, let's do it cleanly:
                nearest_idx = sindex.nearest(geom, return_all=False)[1]
                neighbors = gdf.iloc[nearest_idx]
                neighbors = neighbors[neighbors.index != idx].head(3)
                
                if len(neighbors) > 0:
                    for col in num_with_nans:
                        if pd.isna(gdf.at[idx, col]):
                            neighbor_vals = neighbors[col].dropna()
                            if len(neighbor_vals) > 0:
                                gdf.at[idx, col] = neighbor_vals.mean()
                                imputed_tracker[idx].append(col)
                                
                    for col in cat_with_nans:
                        val = gdf.at[idx, col]
                        if is_cat_nan(val):
                            neighbor_vals = neighbors[col].dropna()
                            neighbor_vals = neighbor_vals[~neighbor_vals.isin(['UNKNOWN', 'unknown', 'Unknown', ''])]
                            if len(neighbor_vals) > 0:
                                mode_val = neighbor_vals.mode()
                                if not mode_val.empty:
                                    gdf.at[idx, col] = mode_val.iloc[0]
                                    imputed_tracker[idx].append(col)

        # 2. Global Imputation (Second tier)
        # Instead of 0, we use global median or mean for continuous variables.
        # But for POI counts, missing might mean 0 if the API returned empty, 
        # so we default POIs to 0 but default speeds/densities to means.
        
        global_impute_vals = {}
        for col in num_with_nans:
            non_na = gdf[col].dropna()
            if col.startswith('POI_') or col.startswith('OSM_') or col.startswith('Mapillary_'):
                global_impute_vals[col] = 0.0 # It's a count, 0 is a safe assumption if no neighbors had it
            elif 'Speed' in col or 'Percentile' in col:
                global_impute_vals[col] = non_na.median() if not non_na.empty else 50.0
            else:
                global_impute_vals[col] = non_na.mean() if not non_na.empty else 0.0
            
        global_modes = {}
        for col in cat_with_nans:
            non_na = gdf[col].dropna()
            non_na = non_na[~non_na.isin(['UNKNOWN', 'unknown', 'Unknown', ''])]
            global_modes[col] = non_na.mode().iloc[0] if not non_na.empty else ('secondary' if col == 'RoadClass' else 'URBAN')

        for col in num_with_nans:
            nan_rows = gdf[gdf[col].isna()].index
            if len(nan_rows) > 0:
                gdf.loc[nan_rows, col] = global_impute_vals[col]
                for idx in nan_rows:
                    imputed_tracker[idx].append(col)
                    
        for col in cat_with_nans:
            is_nan_mask = gdf[col].apply(is_cat_nan)
            nan_rows = gdf[is_nan_mask].index
            if len(nan_rows) > 0:
                gdf.loc[nan_rows, col] = global_modes[col]
                for idx in nan_rows:
                    imputed_tracker[idx].append(col)

        # Ensure strings are properly joined into comma separated format
        # Filter out empty lists to avoid purely empty trailing commas if appending
        gdf['ImputedFields'] = [",".join(imputed_tracker.get(idx, [])) for idx in gdf.index]

        # 3. Cross-validate PercentOverLimit against speed metrics
        # If F85 > SpeedLimit, at least 15% of drivers exceed the limit by definition.
        # If MedianSpeed > SpeedLimit, at least 50% exceed the limit.
        # We estimate the true percentage using a normal distribution CDF derived
        # from the 85th-percentile and median speeds.
        if 'PercentOverLimit' in gdf.columns and 'F85thPercentileSpeed' in gdf.columns and 'SpeedLimit' in gdf.columns:
            from scipy.stats import norm as _norm
            print("    [DataCleaner] Cross-validating PercentOverLimit against speed metrics...")
            corrected_count = 0

            speed_limit = pd.to_numeric(gdf['SpeedLimit'], errors='coerce').fillna(50.0)
            f85 = pd.to_numeric(gdf['F85thPercentileSpeed'], errors='coerce').fillna(speed_limit)
            median = pd.to_numeric(gdf.get('MedianSpeed', speed_limit), errors='coerce').fillna(speed_limit)
            pct_over = pd.to_numeric(gdf['PercentOverLimit'], errors='coerce').fillna(0.0)

            # Vectorised estimation using normal CDF
            # sigma = (F85 - Median) / 1.0364  (z_0.85 ≈ 1.0364)
            sigma = (f85 - median) / 1.0364
            sigma = sigma.clip(lower=0.5)  # floor to avoid division issues

            z_scores = (speed_limit - median) / sigma
            estimated_pct = 1.0 - _norm.cdf(z_scores)
            estimated_pct = estimated_pct.clip(0.0, 1.0)

            # Conditions where the current value is inconsistent
            needs_fix = (
                ((pct_over <= 0.0) & (f85 > speed_limit)) |
                ((f85 > speed_limit) & (pct_over < 0.15)) |
                ((median > speed_limit) & (pct_over < 0.50))
            )

            gdf.loc[needs_fix, 'PercentOverLimit'] = estimated_pct[needs_fix]
            corrected_count = int(needs_fix.sum())
            if corrected_count > 0:
                print(f"    [DataCleaner] Corrected PercentOverLimit for {corrected_count} segments using normal-CDF estimation.")

        print("[DataCleaner] Imputation complete.")
        return gdf
