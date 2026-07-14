import sys
import pandas as pd
import json

def generate_analytics(geojson_path):
    print(f"--- POST-PHASE LIFECYCLE HOOK: Analytics ---")
    try:
        import geopandas as gpd
        gdf = gpd.read_file(geojson_path)
        
        total = len(gdf)
        mean_s3 = gdf['SpeedSafetyScore'].mean()
        median_s3 = gdf['SpeedSafetyScore'].median()
        high_risk = len(gdf[gdf['SpeedSafetyScore'] < 40])
        pct = (high_risk / total) * 100 if total > 0 else 0
        
        print(f"Total Segments: {total:,}")
        print(f"Mean S3:        {mean_s3:.2f}")
        print(f"Median S3:      {median_s3:.2f}")
        print(f"High Priority:  {high_risk:,} ({pct:.2f}%)")
        print("---------------------------------------------")
        
    except Exception as e:
        print(f"Hook Failed: Could not process {geojson_path}. Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_analytics(sys.argv[1])
    else:
        print("Usage: python post_analytics.py <scored.geojson>")
