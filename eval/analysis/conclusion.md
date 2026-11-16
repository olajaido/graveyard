report_sha256: 411a9a165edfca9ca69778002a3d76fa9e7d4847e8a0c8e34fd0ad6bf1ac862c

# Conclusion of the v1 failure analysis (maintainer, 16 Nov 2026)

In-sample diagnostic on the v1 answer key; not validation.

## Finding
Score-based Dead was correct for 13 of 30 rows. Correct and incorrect score-based Dead rows have near-identical risk profiles: for long-quiet repositories with no recent committers and a Scorecard Maintained score of 0, r2, r3, r4 and r5 saturate at 1.0 and mortality lands around 86-90 whatever the true state (for example react-hooks-global-state, dead, 87.2; updeep, finished-healthy, 88.0; vue-formly, ailing, 87.9). The scored signals carry no information that separates abandoned from finished or ailing packages once they saturate.

## On the working hypothesis
"Inactivity treated as death" is supported only in part. Removing staleness made the result worse (finished-healthy predicted Dead 11 -> 15); removing Scorecard improved it (11 -> 8) without fixing it. Inactivity enters through several saturating signals at once, including Scorecard's Maintained check; no single signal is the cause.

## Direction for v2
Death is pronounced only on a declaration: without S1 (registry deprecation or archived repository), the most severe base state is Ailing. Mortality, Resting and the Ailing/Alive boundaries are otherwise as in v1. Declared-Dead precision was 27/28 in v1.

## Trade-off and safeguard
Undeclared dead packages become Ailing, not Dead; they remain flagged. Because the gate rewards withholding Dead, a pre-registered held-out check is added before the v2 freeze: at least 0.85 of labelled dead rows must be flagged Dead or Ailing (v1 on the v1 key: 41/45).
