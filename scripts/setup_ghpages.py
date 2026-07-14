import json
import os
import math
import argparse

def split_geojson(filepath, max_chunk_mb=45, docs_dir=None):
    """Split a GeoJSON FeatureCollection into multiple files, each under max_chunk_mb."""
    if docs_dir is None:
        docs_dir = os.path.dirname(filepath)
        
    basename = os.path.basename(filepath)
    name_no_ext = os.path.splitext(basename)[0]
    
    if not os.path.exists(filepath):
        print(f"Warning: File not found for splitting: {filepath}")
        return []
        
    print(f"Loading {basename}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    features = data['features']
    total = len(features)
    print(f"  Total features: {total}")
    
    # Estimate size per feature
    total_size = os.path.getsize(filepath)
    avg_feature_size = total_size / total
    features_per_chunk = int((max_chunk_mb * 1024 * 1024) / avg_feature_size)
    num_chunks = math.ceil(total / features_per_chunk)
    
    print(f"  File size: {total_size/1024/1024:.1f} MB")
    print(f"  Avg feature size: {avg_feature_size:.0f} bytes")
    print(f"  Features per chunk: {features_per_chunk}")
    print(f"  Number of chunks: {num_chunks}")
    
    chunk_files = []
    for i in range(num_chunks):
        start = i * features_per_chunk
        end = min(start + features_per_chunk, total)
        chunk = {
            "type": "FeatureCollection",
            "features": features[start:end]
        }
        chunk_name = f"{name_no_ext}_part{i+1}.geojson"
        chunk_path = os.path.join(docs_dir, chunk_name)
        
        with open(chunk_path, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, separators=(',', ':'))
        
        chunk_size = os.path.getsize(chunk_path)
        print(f"  Wrote {chunk_name}: {chunk_size/1024/1024:.1f} MB ({end-start} features)")
        chunk_files.append(chunk_name)
    
    return chunk_files

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
    args = parser.parse_args()
    docs_dir = args.docs_dir
    
    print(f"Starting GeoJSON splitting in: {docs_dir}")
    # Split the optimized network GeoJSON
    opt_path = os.path.join(docs_dir, "makenes_scored_optimized.geojson")
    opt_chunks = split_geojson(opt_path, docs_dir=docs_dir)
    
    # Split the conflicts GeoJSON
    conf_path = os.path.join(docs_dir, "makenes_scored_conflicts.geojson")
    conf_chunks = split_geojson(conf_path, docs_dir=docs_dir)
    
    print(f"\nOptimized chunks: {opt_chunks}")
    print(f"Conflicts chunks: {conf_chunks}")

if __name__ == '__main__':
    main()
