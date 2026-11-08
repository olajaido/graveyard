"""Formula-shape constants for the mortality model.

These constants define the structure of the scoring formula. They are not
tunable parameters and they do not change between model versions. All tunable
parameters (weights, thresholds, exposure multipliers, cursed multiplier) live
in ``weights.v1.yaml``.
"""

# r5: bus-factor risk buckets (distinct committers -> risk).
# Committers >= 5 map to 0.0; the consumer handles that case.
R5_BUCKETS: dict[int, float] = {0: 1.0, 1: 1.0, 2: 0.6, 3: 0.3, 4: 0.3}

# r6: open-ratio midpoint for the issue-neglect formula.
R6_MIDPOINT: float = 0.5
