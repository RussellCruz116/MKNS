import numpy as np

# Safe System Survivable Speed Thresholds (km/h)
SURVIVABLE_SPEEDS = {
    'vru_conflict': 30,
    'side_impact': 50,
    'frontal_impact': 70,
    'no_conflict': 100
}

FATALITY_MODELS = {
    'pedestrian': {'b0': -10.204, 'b1': 0.099, 'b2': 0.053},
    'cyclist': {'b0': -10.674, 'b1': 0.100, 'b2': 0.053},
    'motorcyclist': {'b0': -7.494, 'b1': 0.047, 'b2': 0.014},
    'car_driver_frontal': {'b0': -9.645, 'b1': 0.044, 'b2': 0.021}
}

def calculate_fatality_probability(user_class: str, closing_speed_kmh: float, age: int = 30) -> float:
    if user_class not in FATALITY_MODELS:
        raise ValueError(f"Unknown user class: {user_class}")
    model = FATALITY_MODELS[user_class]
    logit = model['b0'] + (model['b1'] * closing_speed_kmh) + (model['b2'] * age)
    return 1.0 / (1.0 + np.exp(-logit))

def calculate_idm_acceleration(v, v_max, s, delta_v, T, a_max, b_des, s0):
    """
    Intelligent Driver Model (IDM) Kinematics.
    v: current velocity
    v_max: desired velocity
    s: current gap to lead vehicle
    delta_v: velocity difference
    T: safe time headway
    a_max: max acceleration
    b_des: desired deceleration
    s0: minimum gap
    """
    if v_max <= 0:
        return 0.0
    s_star = s0 + v * T + (v * delta_v) / (2 * np.sqrt(a_max * b_des))
    acceleration = a_max * (1 - (v / v_max)**4 - (s_star / max(s, 0.1))**2)
    return acceleration

def calculate_sfm_repulsion(distance, repulsion_strength=2.0):
    """
    Social Force Model (SFM) Psychological Repulsion
    Returns deceleration scalar based on proximity to VRU.
    """
    dist_clamped = max(distance, 0.0001)
    return - (repulsion_strength / dist_clamped)
