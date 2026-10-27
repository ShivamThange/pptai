import copy
import hashlib
import json

import yaml


DEFAULT = {
    "embedding": {"model": "sentence-transformers/all-MiniLM-L6-v2"},
    "coverage": {"covered_threshold": .65, "partial_threshold": .45, "partial_credit": .5},
    "faithfulness": {"enabled": True, "top_k_evidence": 5, "judge_provider": None, "judge_model": None, "temperature": 0.0},
    "visual": {"safe_margin_inches": .25, "overlap_ratio": .05, "body_small_font_pt": 14, "dense_words": 180,
               "density_min": .15, "density_max": .9},
    "aggregate": {"weights": {"semantic": .2, "coverage": .3, "faithfulness": .2, "functional": .1, "structure": .1, "visual": .1}},
}


def _merge(base, update):
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict): _merge(base[key], value)
        else: base[key] = value
    return base


def load(path=None):
    config = copy.deepcopy(DEFAULT)
    if path:
        with open(path, encoding="utf-8") as f: _merge(config, yaml.safe_load(f) or {})
    c = config["coverage"]
    if not 0 <= c["partial_threshold"] <= c["covered_threshold"] <= 1: raise ValueError("Invalid coverage thresholds")
    return config


def digest(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
