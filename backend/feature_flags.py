# ── LOCAL ONLY — this entire file has no upstream equivalent ──
"""Feature gating for the local-only migration.

Implements Phase 10 of the migration spec: rather than ripping out cloud-only
subsystems (which would be a much larger refactor), each feature has an
``ENABLE_<NAME>`` flag that defaults to ``true`` for backward compatibility but
can be flipped off in local mode.

Routers that touch a non-core feature should call ``ensure_enabled(name)``;
disabled features then fail with an explicit ``FeatureDisabled`` error rather
than crashing the app at import time.

Spec reference: omi_local_backend_merged_final.md §"Phase 10 — Remove Non-Core
Cloud Features".
"""

import os
from typing import Dict


class FeatureDisabled(RuntimeError):
    pass


# Default-on so existing cloud deployments are unaffected. Local mode flips
# everything off via .env.template.
_DEFAULTS: Dict[str, bool] = {
    "billing": True,
    "stripe": True,
    "mixpanel": True,
    "hume": True,
    "perplexity": True,
    "langsmith": True,
    "rapidapi": True,
    "pusher_hosted": True,
    "modal": True,
    "google_maps": True,
    "github_token": True,
    "whoop_oauth": True,
    "notion_oauth": True,
    "google_oauth": True,
    "twitter_oauth": True,
    "typesense": True,
}


def _env_flag(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_enabled(feature: str) -> bool:
    feature = feature.strip().lower()
    if feature not in _DEFAULTS:
        raise KeyError(f"Unknown feature flag: {feature}")
    return _env_flag(f"ENABLE_{feature.upper()}", _DEFAULTS[feature])


def ensure_enabled(feature: str) -> None:
    if not is_enabled(feature):
        raise FeatureDisabled(
            f"Feature '{feature}' is disabled in this configuration. "
            "Set ENABLE_" + feature.upper() + "=true to enable it."
        )


def local_mode_disable_recommended() -> Dict[str, str]:
    """Returns the set of env vars to set when running fully local.

    Operators (or a startup banner) can dump this dict to log so it's clear
    which knobs the migration spec recommends flipping off.
    """
    return {f"ENABLE_{name.upper()}": "false" for name in _DEFAULTS}
