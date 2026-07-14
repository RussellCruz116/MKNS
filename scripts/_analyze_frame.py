import json
from collections import Counter

path = r"C:\Users\Johan\OneDrive\Documents\ADB\makenes_github_package\docs\frame_data.json"
d = json.load(open(path))
sids = list(d.keys())
print("Segment IDs:", sids)

for s in sids:
    frames = d[s]["frames"]
    shape = d[s]["shape"]
    print(f"\n--- Segment {s} ---")
    print(f"  Frames: {len(frames)}, Shape points: {len(shape)}")
    
    # Check shape extent
    if shape:
        sx = [p[0] for p in shape]
        sy = [p[1] for p in shape]
        print(f"  Shape X range: {min(sx):.6f} to {max(sx):.6f} (span={max(sx)-min(sx):.8f} deg, ~{(max(sx)-min(sx))*111320:.1f}m)")
        print(f"  Shape Y range: {min(sy):.6f} to {max(sy):.6f} (span={max(sy)-min(sy):.8f} deg, ~{(max(sy)-min(sy))*111320:.1f}m)")
    
    # Check frame 0 actor positions
    f0 = frames[0] if frames else []
    print(f"  Frame 0 actors: {len(f0)}")
    if f0:
        types = [a["type"] for a in f0]
        print(f"  Types: {Counter(types)}")
        xs = [a["x"] for a in f0]
        ys = [a["y"] for a in f0]
        print(f"  Actor X range: {min(xs):.6f} to {max(xs):.6f} (span={max(xs)-min(xs):.8f} deg, ~{(max(xs)-min(xs))*111320:.1f}m)")
        print(f"  Actor Y range: {min(ys):.6f} to {max(ys):.6f} (span={max(ys)-min(ys):.8f} deg, ~{(max(ys)-min(ys))*111320:.1f}m)")
    
    # Also check a mid-frame
    mid = len(frames) // 2
    fm = frames[mid] if mid < len(frames) else []
    print(f"  Frame {mid} actors: {len(fm)}")
    if fm:
        xs = [a["x"] for a in fm]
        ys = [a["y"] for a in fm]
        print(f"  Mid Actor X range: {min(xs):.6f} to {max(xs):.6f} (span={max(xs)-min(xs):.8f} deg, ~{(max(xs)-min(xs))*111320:.1f}m)")
        print(f"  Mid Actor Y range: {min(ys):.6f} to {max(ys):.6f} (span={max(ys)-min(ys):.8f} deg, ~{(max(ys)-min(ys))*111320:.1f}m)")
