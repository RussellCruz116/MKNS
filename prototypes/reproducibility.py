"""
Deterministic execution helpers for reproducible S³ scoring and ABM runs.
"""

import hashlib
import json
import os
import random

import numpy as np

DEFAULT_SEED = 42
LLM_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cache",
    "board_evaluations.json",
)


def is_deterministic() -> bool:
    return os.environ.get("MAKENES_DETERMINISTIC", "").strip() in ("1", "true", "yes")


def use_llm_cache() -> bool:
    if os.environ.get("MAKENES_LLM_CACHE", "").strip() in ("1", "true", "yes"):
        return True
    return is_deterministic()


def set_deterministic(seed: int = DEFAULT_SEED) -> None:
    """Fix Python, NumPy, and ABM random state for reproducible runs."""
    os.environ["MAKENES_DETERMINISTIC"] = "1"
    os.environ.setdefault("MAKENES_LLM_CACHE", "1")
    random.seed(seed)
    np.random.seed(seed)


def archetype_cache_key(archetypes: dict) -> str:
    """Stable hash of archetype inputs for LLM response caching."""
    payload = json.dumps(archetypes, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_llm_cache(cache_key: str) -> dict | None:
    if not use_llm_cache() or not os.path.exists(LLM_CACHE_PATH):
        return None
    try:
        with open(LLM_CACHE_PATH, encoding="utf-8") as f:
            store = json.load(f)
        return store.get(cache_key)
    except (json.JSONDecodeError, OSError):
        return None


def save_llm_cache(cache_key: str, genai_outputs: dict) -> None:
    if not is_deterministic():
        return
    os.makedirs(os.path.dirname(LLM_CACHE_PATH), exist_ok=True)
    store = {}
    if os.path.exists(LLM_CACHE_PATH):
        try:
            with open(LLM_CACHE_PATH, encoding="utf-8") as f:
                store = json.load(f)
        except (json.JSONDecodeError, OSError):
            store = {}
    store[cache_key] = genai_outputs
    with open(LLM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
