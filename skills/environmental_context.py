import random

class EnvironmentalContext:
    """
    Skill for inferring environmental conditions (weather, time of day)
    to add complexity to the AI Agent scoring rubric.
    """
    def __init__(self):
        # We can simulate different weather patterns or time-of-day risks
        pass

    def extract_environmental_risk(self, arch_data, inferred_zone):
        """
        Simulates environmental conditions for an archetype cluster.
        Returns a dictionary of conditions and a risk multiplier.
        """
        # Determine time of day (Night carries higher risk due to visibility)
        is_night = random.random() < 0.3  # 30% chance the evaluation is done for night-time context
        
        # Weather (Rain reduces friction)
        is_raining = random.random() < 0.2 # 20% chance of rain
        
        risk_multiplier = 1.0
        details = []
        
        if is_night:
            details.append("Night-time (Low Visibility)")
            risk_multiplier += 0.15 # 15% increase in baseline risk
            
            # Night is exceptionally dangerous for VRUs if F85 is high
            if arch_data.get('F85', 0) > 60 and "Urban" in inferred_zone:
                risk_multiplier += 0.1
                details.append("High-Speed Urban Night Hazard")
                
        if is_raining:
            details.append("Rain (Reduced Pavement Friction)")
            risk_multiplier += 0.20
            
            if "Rural" in inferred_zone:
                risk_multiplier += 0.1
                details.append("Rural Wet Surface Hazard")

        if not is_night and not is_raining:
            details.append("Clear / Daytime")
            
        return {
            "is_night": is_night,
            "is_raining": is_raining,
            "risk_multiplier": risk_multiplier,
            "details": details
        }
