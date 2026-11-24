"""
User profile: personal details that must not live in source code.

Values come from (highest priority first):
  1. environment variables (JARVIS_OWNER_NAME, JARVIS_CREATOR_NAME, JARVIS_CREATOR_FULL_NAME)
  2. user_profile.json in the project root (gitignored; copy user_profile.example.json)
  3. the defaults below
"""

import logging
_log = logging.getLogger(__name__)

import json
import os
from functools import lru_cache
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parent.parent.parent / "user_profile.json"

DEFAULTS = {
    "owner_name": "Owner",       # who face recognition treats as the owner
    "creator_name": "Raghava",   # public author credit ("I was created by ...")
    "creator_full_name": "",     # only shared when explicitly asked; empty = never
}

_ENV = {
    "owner_name": "JARVIS_OWNER_NAME",
    "creator_name": "JARVIS_CREATOR_NAME",
    "creator_full_name": "JARVIS_CREATOR_FULL_NAME",
}


@lru_cache(maxsize=1)
def get_profile() -> dict:
    profile = dict(DEFAULTS)
    if PROFILE_PATH.exists():
        try:
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            profile.update({k: str(v) for k, v in data.items() if k in DEFAULTS and v is not None})
        except (OSError, ValueError) as e:
            _log.warning(f"[PROFILE] Could not read {PROFILE_PATH.name}: {e}")
    for key, env_var in _ENV.items():
        if os.getenv(env_var):
            profile[key] = os.environ[env_var]
    return profile
