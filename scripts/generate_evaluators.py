import os
import yaml

board_dir = r"C:\Users\Johan\OneDrive\Documents\ADB\makenes_project\skills\board_of_evaluators"
os.makedirs(board_dir, exist_ok=True)

evaluators = [
    {
        "name": "School Zone Guardian",
        "domain": "Pedestrians & Schools",
        "k_modifier": 1.4,
        "w1_mod": 1.2,
        "w2_mod": 0.8,
        "focus": "Pedestrian safety around schools and educational institutions.",
        "global_policy": "WHO Global Status Report on Road Safety - 30 km/h speed limits where vulnerable road users and vehicles mix.",
        "regional_policy": "ADB Transport Sector Guidelines - Safe routes to school initiatives.",
        "local_policy": "Local traffic acts mandating strict 20-30 km/h limits and physical traffic calming near schools."
    },
    {
        "name": "Motorway Specialist",
        "domain": "High-Speed Arterials",
        "k_modifier": 0.8,
        "w1_mod": 0.9,
        "w2_mod": 1.2,
        "focus": "Regulating high-speed multi-lane arterials to prevent fatal head-on and side-impact collisions.",
        "global_policy": "iRAP Star Ratings - Divided highways with physical medians required for speeds > 70 km/h.",
        "regional_policy": "GRSF - Elimination of at-grade U-turns on major arterials.",
        "local_policy": "National Highway Authority regulations on median barriers and access control."
    },
    {
        "name": "VRU Advocate",
        "domain": "Vulnerable Road Users",
        "k_modifier": 1.3,
        "w1_mod": 1.3,
        "w2_mod": 0.9,
        "focus": "Protecting pedestrians, cyclists, and micro-mobility users.",
        "global_policy": "WHO Global Action Plan for Road Safety - Target 4: Achieve more than 75% of travel on safe roads for all road users by 2030.",
        "regional_policy": "ADB Non-Motorized Transport (NMT) frameworks.",
        "local_policy": "Local municipal codes on sidewalk widths, crosswalk intervals, and cycling lanes."
    },
    {
        "name": "Freight Optimizer",
        "domain": "Heavy Goods Vehicles",
        "k_modifier": 1.1,
        "w1_mod": 1.1,
        "w2_mod": 1.1,
        "focus": "Managing the unique kinetic risks posed by trucks and heavy goods vehicles.",
        "global_policy": "Safe System Approach - Kinetic energy management in collisions involving mass disparity.",
        "regional_policy": "ASEAN/ADB freight transport safety guidelines.",
        "local_policy": "Local restrictions on HGV operating hours, lane usage, and weight limits."
    },
    {
        "name": "Nighttime Safety Officer",
        "domain": "Low-Visibility Conditions",
        "k_modifier": 1.2,
        "w1_mod": 1.1,
        "w2_mod": 1.1,
        "focus": "Addressing increased accident severity during nighttime and adverse weather.",
        "global_policy": "WHO Road Safety Guidelines - Adequate street lighting and retroreflective signage.",
        "regional_policy": "ADB Climate-Resilient Transport Guidelines.",
        "local_policy": "Local codes for street lighting lux levels and road marking reflectivity."
    },
    {
        "name": "Urban Planner",
        "domain": "Intersections & Congestion",
        "k_modifier": 1.0,
        "w1_mod": 0.9,
        "w2_mod": 1.3,
        "focus": "Mitigating side-impact collisions at complex urban intersections and optimizing traffic flow.",
        "global_policy": "iRAP - Safe intersection design to reduce impact angles to < 30 degrees.",
        "regional_policy": "GRSF Intersection Safety and ADB Urban Mobility frameworks.",
        "local_policy": "Local traffic signal timing, turning restrictions, and low-emission zone calming."
    },
    {
        "name": "Rural Highway Patrol",
        "domain": "Rural Roads",
        "k_modifier": 0.9,
        "w1_mod": 1.2,
        "w2_mod": 0.9,
        "focus": "Preventing high-speed run-off-road and head-on crashes on undivided rural roads.",
        "global_policy": "iRAP - Audio-tactile edge lines and centerline rumble strips.",
        "regional_policy": "ADB Rural Road Safety Action Plans.",
        "local_policy": "National standards for rural road geometry and clear zones."
    },
    {
        "name": "Vision Zero Director",
        "domain": "System-wide Safety",
        "k_modifier": 1.5,
        "w1_mod": 1.2,
        "w2_mod": 1.2,
        "focus": "Holistic system-wide safety aiming for zero fatalities.",
        "global_policy": "Vision Zero / Safe System Approach core philosophy.",
        "regional_policy": "Regional adoption of Vision Zero targets by 2030.",
        "local_policy": "National road safety strategies and targets."
    },
    {
        "name": "Two-Wheeler Rep",
        "domain": "Powered Two-Wheelers",
        "k_modifier": 1.2,
        "w1_mod": 1.1,
        "w2_mod": 1.2,
        "focus": "Addressing the high proportion of Powered Two-Wheeler (PTW) fatalities.",
        "global_policy": "WHO - Helmet laws and dedicated motorcycle infrastructure.",
        "regional_policy": "ADB specific focus on the Asia-Pacific PTW epidemic.",
        "local_policy": "Local motorcycle lane regulations and helmet enforcement."
    },
    {
        "name": "Public Transit Liaison",
        "domain": "Public Transit",
        "k_modifier": 1.0,
        "w1_mod": 1.0,
        "w2_mod": 1.0,
        "focus": "Ensuring safety around bus stops and transit corridors.",
        "global_policy": "WHO - Safe public transport access.",
        "regional_policy": "ADB Sustainable Transport Initiative.",
        "local_policy": "Local transit authority safety guidelines."
    }
]

for evaluator in evaluators:
    filename = evaluator["name"].lower().replace(" ", "_").replace("(", "").replace(")", "").replace("&", "and").replace("-", "_") + ".md"
    filepath = os.path.join(board_dir, filename)
    
    frontmatter = {
        "name": evaluator["name"],
        "domain": evaluator["domain"],
        "k_modifier": evaluator["k_modifier"],
        "w1_mod": evaluator["w1_mod"],
        "w2_mod": evaluator["w2_mod"]
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(frontmatter, f, default_flow_style=False)
        f.write("---\n\n")
        f.write(f"# {evaluator['name']}\n\n")
        f.write(f"**Focus:** {evaluator['focus']}\n\n")
        f.write(f"## Policy Grounding\n\n")
        f.write(f"### 1. Global Policy\n{evaluator['global_policy']}\n\n")
        f.write(f"### 2. Regional Policy (Asia-Pacific)\n{evaluator['regional_policy']}\n\n")
        f.write(f"### 3. Local Policy Alignment\n{evaluator['local_policy']}\n\n")
        f.write(f"## Scoring Configuration Limits\n")
        f.write(f"- **w1_mod_bounds**: [0.8, 1.2]\n")
        f.write(f"- **w2_mod_bounds**: [0.8, 1.2]\n")
        f.write(f"- **k_modifier_max**: 1.5\n")
        f.write(f"\n*Note: Weight modifications must represent a trade-off. Extreme inflation is monitored.*")
