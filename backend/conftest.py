"""Shared pytest configuration: Hypothesis profiles."""

import os

from hypothesis import settings

_PROFILES: dict[str, int] = {"ci": 500, "dev": 200}
_DEFAULT_PROFILE = "dev"

for _name, _max_examples in _PROFILES.items():
    settings.register_profile(_name, max_examples=_max_examples)


def _select_profile() -> str:
    name = os.environ.get("HYPOTHESIS_PROFILE", _DEFAULT_PROFILE)
    if name not in _PROFILES:
        raise RuntimeError(
            f"Unknown HYPOTHESIS_PROFILE {name!r}; expected one of {sorted(_PROFILES)}"
        )
    return name


settings.load_profile(_select_profile())
