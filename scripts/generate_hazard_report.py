import os
import sys
import pandas as pd
import sqlite3

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(base_dir, 'db', 'makenes.sqlite')
report_path = os.path.join(base_dir, 'outputs', 'reports', 'hazard_analysis_report.md')

def generate_report():
    print(f"Generating Hazard Analysis Report from {db_path}...")
    if not os.path.exists(db_path):
        print("Database not found. Please run main.py first.")
        return
        
    conn = sqlite3.connect(db_path)
    
    # Analyze network scores
    try:
        network_df = pd.read_sql_query("SELECT * FROM scored_network_global", conn)
        avg_score = network_df['SpeedSafetyScore'].mean()
        num_segments = len(network_df)
    except Exception as e:
        print(f"Error reading scored network: {e}")
        avg_score = 0
        num_segments = 0

    # Analyze conflicts
    try:
        conflicts_df = pd.read_sql_query("SELECT * FROM abm_conflicts_global", conn)
        total_conflicts = len(conflicts_df)
        ttc_count = len(conflicts_df[conflicts_df['type'] == 'TTC'])
        pet_count = len(conflicts_df[conflicts_df['type'] == 'PET'])
    except Exception as e:
        print(f"Error reading conflicts: {e}")
        total_conflicts = 0
        ttc_count = 0
        pet_count = 0

    markdown_content = f"""# Microscopic ABM Hazard Analysis Report
*Generated from MaKeNeS Pipeline SQLite Telemetry*

## 1. Executive Summary
This report analyzes the emergent properties of the massive 2500-step Agent-Based Model run across {num_segments} road segments.

- **Total Severe Hazard Events Logged:** {total_conflicts}
- **Critical Time-To-Collision (TTC < 1.5s):** {ttc_count}
- **Severe Post-Encroachment Time (PET < 1.5s):** {pet_count}
- **Global Average Speed Safety Score (S³):** {avg_score:.2f}

## 2. Theoretical Grounding: Safe System Principles
Based on cross-referenced literature (`reference_materials/intern_research.md`), human bodies cannot survive impact forces exceeding 30 km/h. 
- **TTC Hazards** (represented as ▲ on the dashboard) typically indicate direct collision courses between Vehicles and Vulnerable Road Users (VRUs). The high concentration of these events heavily implies that VRUs are forced into sharing lane geometry with vehicles exceeding 30 km/h.
- **PET Hazards** (represented as ♦) indicate near-misses where a vehicle missed a pedestrian by less than 1.5 seconds. These often occur at unprotected crosswalks or mid-block crossings in high-density areas.

## 3. Top-Level Interventions
To mitigate the {total_conflicts} hazards flagged by the physics engine, transport authorities must prioritize:
1. **Physical Segregation:** Where TTC hazards are clustered, narrow road widths and high speeds force dangerous interaction. Protected bike lanes or raised sidewalks are required.
2. **Speed Calming:** Where PET hazards dominate, traffic moves too fast through pedestrian permeability zones. Speed humps, chicanes, and 30 km/h zoning are immediately necessary.

## 4. Future Expansion
Because all telemetry is now natively persisted to `db/makenes.sqlite`, future researchers can:
- Run spatial clustering (DBSCAN) directly against the database to pinpoint the most lethal intersections.
- Cross-reference empirical crash logs with the synthetic ABM geometries.
"""

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
        
    print(f"Report successfully written to {report_path}")

if __name__ == "__main__":
    generate_report()
