In-sample diagnostic on the v1 answer key. Not validation.

# v1 failure analysis

- model: v1; as of: 2026-11-13
- weights sha256: f1e5d7f1e821c1091e24e892b4924b1649fa57917296d6411df0369015c27c4f
- labels sha256: 8a0c91afdd4585a8d75c5fb2a7f0ae4407215cbd614b15aaa4ec84d7f4de6f85
- rows: 116; misclassified: 37

## Recorded result

| metric | n/d | value | 95% Wilson |
|---|---|---|---|
| Dead precision | 40/58 | 0.690 | 0.562 to 0.794 |
| Finished-healthy FPR | 11/20 | 0.550 | 0.342 to 0.742 |

## Confusion matrix

| label \ predicted | dead | finished-healthy | alive | ailing | unknown |
|---|---|---|---|---|---|
| dead | 40 | 1 | 3 | 1 | 0 |
| finished-healthy | 11 | 3 | 1 | 5 | 0 |
| alive | 0 | 0 | 31 | 0 | 0 |
| ailing | 7 | 4 | 4 | 5 | 0 |

Misclassified by pair: ailing->alive: 4, ailing->dead: 7, ailing->finished-healthy: 4, dead->ailing: 1, dead->alive: 3, dead->finished-healthy: 1, finished-healthy->ailing: 5, finished-healthy->alive: 1, finished-healthy->dead: 11

## Misclassified rows

| row | label | predicted | mortality | dominant signal | groups |
|---|---|---|---|---|---|
| npm/animate-components@1.4.8 | ailing | dead | 88.5 | r2 | staleness 0.56, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.10 |
| npm/graphql-list-fields@2.0.4 | finished-healthy | dead | 61.7 | r2 | staleness 0.40, maintenance 0.32, bus_factor 0.16, issues 0.00, scorecard 0.11 |
| npm/karma@6.4.4 | dead | finished-healthy | 51.6 | r4 | staleness 0.31, maintenance 0.39, bus_factor 0.19, issues 0.00, scorecard 0.11 |
| npm/material-design-lite@1.3.0 | ailing | dead | 60.4 | r2 | staleness 0.41, maintenance 0.33, bus_factor 0.17, issues 0.00, scorecard 0.09 |
| npm/pdfjs@2.5.4 | ailing | finished-healthy | 46.3 | r4 | staleness 0.20, maintenance 0.43, bus_factor 0.22, issues 0.00, scorecard 0.15 |
| npm/please-upgrade-node@3.2.0 | finished-healthy | dead | 63.0 | r2 | staleness 0.40, maintenance 0.32, bus_factor 0.16, issues 0.00, scorecard 0.13 |
| npm/react-accessible-details@3.0.5 | finished-healthy | dead | 100.0 | r2 | staleness 1.00, maintenance 0.00, bus_factor 0.00, issues 0.00, scorecard 0.00 |
| npm/react-native-version-check@3.5.0 | ailing | finished-healthy | 43.0 | r4 | staleness 0.16, maintenance 0.47, bus_factor 0.23, issues 0.00, scorecard 0.15 |
| npm/rx-sandbox@2.0.5 | finished-healthy | dead | 86.8 | r2 | staleness 0.58, maintenance 0.23, bus_factor 0.12, issues 0.00, scorecard 0.08 |
| npm/serializr@3.0.5 | ailing | finished-healthy | 50.7 | r4 | staleness 0.27, maintenance 0.39, bus_factor 0.20, issues 0.00, scorecard 0.14 |
| npm/smells-code-analyzer@0.1.1 | dead | alive | 16.3 | r5 | staleness 0.12, maintenance 0.00, bus_factor 0.88, issues 0.00, scorecard 0.00 |
| npm/stwui@0.21.2-next | finished-healthy | ailing | 47.1 | r2 | staleness 0.70, maintenance 0.00, bus_factor 0.30, issues 0.00, scorecard 0.00 |
| npm/susy-sass@2.4.0 | finished-healthy | alive | 14.3 | r5 | staleness 0.00, maintenance 0.00, bus_factor 1.00, issues 0.00, scorecard 0.00 |
| npm/updeep@1.2.4 | finished-healthy | dead | 88.0 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.09 |
| npm/vue-formly@2.5.9 | ailing | dead | 87.9 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.09 |
| npm/xmldom@0.6.0 | dead | alive | 27.4 | r2 | staleness 0.91, maintenance 0.00, bus_factor 0.00, issues 0.00, scorecard 0.09 |
| pypi/ansible-bender@0.10.1 | ailing | dead | 60.0 | r2 | staleness 0.42, maintenance 0.33, bus_factor 0.17, issues 0.00, scorecard 0.08 |
| pypi/auto-resizing-text-edit@0.1.0 | finished-healthy | dead | 100.0 | r2 | staleness 0.71, maintenance 0.00, bus_factor 0.14, issues 0.14, scorecard 0.00 |
| pypi/django-context-decorator@1.6.1 | finished-healthy | dead | 80.5 | r2 | staleness 0.52, maintenance 0.25, bus_factor 0.12, issues 0.00, scorecard 0.10 |
| pypi/eventlet@0.41.3 | ailing | alive | 12.0 | r4 | staleness 0.00, maintenance 0.67, bus_factor 0.00, issues 0.00, scorecard 0.33 |
| pypi/flask-script@2.0.6 | ailing | dead | 90.0 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.09 |
| pypi/fortls@3.2.2 | ailing | alive | 11.8 | r2 | staleness 1.00, maintenance 0.00, bus_factor 0.00, issues 0.00, scorecard 0.00 |
| pypi/maccarone@0.1.9 | finished-healthy | dead | 100.0 | r2 | staleness 0.71, maintenance 0.00, bus_factor 0.14, issues 0.14, scorecard 0.00 |
| pypi/mapdamage@2.2.3 | ailing | alive | 26.2 | r5 | staleness 0.46, maintenance 0.00, bus_factor 0.54, issues 0.00, scorecard 0.00 |
| pypi/mkdocs-multirepo-plugin@0.8.3 | ailing | finished-healthy | 37.3 | r2 | staleness 0.60, maintenance 0.00, bus_factor 0.38, issues 0.02, scorecard 0.00 |
| pypi/opentaxii@0.9.3 | finished-healthy | ailing | 57.2 | r2 | staleness 0.44, maintenance 0.35, bus_factor 0.10, issues 0.00, scorecard 0.11 |
| pypi/pandoc-mustache@0.1.0 | ailing | dead | 73.1 | r2 | staleness 0.49, maintenance 0.27, bus_factor 0.14, issues 0.00, scorecard 0.10 |
| pypi/products-zopetree@3.4.0 | finished-healthy | dead | 61.3 | r2 | staleness 0.41, maintenance 0.33, bus_factor 0.16, issues 0.00, scorecard 0.10 |
| pypi/pydora@2.3.2 | finished-healthy | ailing | 36.9 | r4 | staleness 0.00, maintenance 0.54, bus_factor 0.27, issues 0.00, scorecard 0.19 |
| pypi/pysoundanalyser@0.3.7 | dead | ailing | 59.4 | r2 | staleness 0.56, maintenance 0.00, bus_factor 0.24, issues 0.20, scorecard 0.00 |
| pypi/pyutilib@6.0.0 | ailing | dead | 65.1 | r2 | staleness 0.39, maintenance 0.31, bus_factor 0.15, issues 0.06, scorecard 0.09 |
| pypi/rai-workflow-manager@0.0.52 | dead | alive | 27.7 | r5 | staleness 0.48, maintenance 0.00, bus_factor 0.52, issues 0.00, scorecard 0.00 |
| pypi/robotframework-angularjs@1.0.0 | finished-healthy | dead | 75.8 | r2 | staleness 0.81, maintenance 0.00, bus_factor 0.19, issues 0.00, scorecard 0.00 |
| pypi/torf@4.3.1 | finished-healthy | ailing | 31.7 | r4 | staleness 0.00, maintenance 0.57, bus_factor 0.19, issues 0.00, scorecard 0.24 |
| pypi/windows-curses@2.4.2 | ailing | alive | 8.6 | r5 | staleness 0.00, maintenance 0.00, bus_factor 1.00, issues 0.00, scorecard 0.00 |
| pypi/zgw-consumers-oas@1.1.0 | finished-healthy | ailing | 30.9 | r5 | staleness 0.54, maintenance 0.00, bus_factor 0.46, issues 0.00, scorecard 0.00 |
| pypi/zilch@0.1.3 | finished-healthy | dead | 97.9 | r2 | staleness 0.51, maintenance 0.20, bus_factor 0.10, issues 0.10, scorecard 0.08 |

## Score-based Dead rows

Correct: 13; incorrect: 17.

| row | label | correct | mortality | dominant signal | groups |
|---|---|---|---|---|---|
| npm/animate-components@1.4.8 | ailing | no | 88.5 | r2 | staleness 0.56, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.10 |
| npm/custom-protocol-detection@1.0.1 | dead | yes | 90.5 | r2 | staleness 0.55, maintenance 0.22, bus_factor 0.11, issues 0.03, scorecard 0.09 |
| npm/graphql-list-fields@2.0.4 | finished-healthy | no | 61.7 | r2 | staleness 0.40, maintenance 0.32, bus_factor 0.16, issues 0.00, scorecard 0.11 |
| npm/material-design-lite@1.3.0 | ailing | no | 60.4 | r2 | staleness 0.41, maintenance 0.33, bus_factor 0.17, issues 0.00, scorecard 0.09 |
| npm/nodejs-mobile-gyp@0.4.0 | dead | yes | 87.2 | r3 | staleness 0.51, maintenance 0.23, bus_factor 0.11, issues 0.06, scorecard 0.09 |
| npm/please-upgrade-node@3.2.0 | finished-healthy | no | 63.0 | r2 | staleness 0.40, maintenance 0.32, bus_factor 0.16, issues 0.00, scorecard 0.13 |
| npm/react-accessible-details@3.0.5 | finished-healthy | no | 100.0 | r2 | staleness 1.00, maintenance 0.00, bus_factor 0.00, issues 0.00, scorecard 0.00 |
| npm/react-hooks-global-state@2.1.0 | dead | yes | 87.2 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.08 |
| npm/rx-sandbox@2.0.5 | finished-healthy | no | 86.8 | r2 | staleness 0.58, maintenance 0.23, bus_factor 0.12, issues 0.00, scorecard 0.08 |
| npm/updeep@1.2.4 | finished-healthy | no | 88.0 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.09 |
| npm/vue-formly@2.5.9 | ailing | no | 87.9 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.09 |
| pypi/ansible-bender@0.10.1 | ailing | no | 60.0 | r2 | staleness 0.42, maintenance 0.33, bus_factor 0.17, issues 0.00, scorecard 0.08 |
| pypi/appdirs@1.4.4 | dead | yes | 86.4 | r2 | staleness 0.58, maintenance 0.23, bus_factor 0.12, issues 0.00, scorecard 0.07 |
| pypi/auto-resizing-text-edit@0.1.0 | finished-healthy | no | 100.0 | r2 | staleness 0.71, maintenance 0.00, bus_factor 0.14, issues 0.14, scorecard 0.00 |
| pypi/django-context-decorator@1.6.1 | finished-healthy | no | 80.5 | r2 | staleness 0.52, maintenance 0.25, bus_factor 0.12, issues 0.00, scorecard 0.10 |
| pypi/feedjack@16.8.1 | dead | yes | 88.0 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.00, scorecard 0.09 |
| pypi/flask-restplus@0.13.0 | dead | yes | 87.4 | r2 | staleness 0.57, maintenance 0.23, bus_factor 0.11, issues 0.01, scorecard 0.07 |
| pypi/kotti-image-gallery@0.3.2 | dead | yes | 85.7 | r2 | staleness 0.83, maintenance 0.00, bus_factor 0.17, issues 0.00, scorecard 0.00 |
| pypi/maccarone@0.1.9 | finished-healthy | no | 100.0 | r2 | staleness 0.71, maintenance 0.00, bus_factor 0.14, issues 0.14, scorecard 0.00 |
| pypi/nose-parameterized@0.6.0 | dead | yes | 77.7 | r2 | staleness 0.52, maintenance 0.26, bus_factor 0.13, issues 0.00, scorecard 0.09 |
| pypi/pandoc-mustache@0.1.0 | ailing | no | 73.1 | r2 | staleness 0.49, maintenance 0.27, bus_factor 0.14, issues 0.00, scorecard 0.10 |
| pypi/pathlib@1.0.1 | dead | yes | 100.0 | r2 | staleness 1.00, maintenance 0.00, bus_factor 0.00, issues 0.00, scorecard 0.00 |
| pypi/ply@3.11 | dead | yes | 100.0 | r2 | staleness 1.00, maintenance 0.00, bus_factor 0.00, issues 0.00, scorecard 0.00 |
| pypi/products-zopetree@3.4.0 | finished-healthy | no | 61.3 | r2 | staleness 0.41, maintenance 0.33, bus_factor 0.16, issues 0.00, scorecard 0.10 |
| pypi/py-d3@0.3.0 | dead | yes | 85.7 | r2 | staleness 0.83, maintenance 0.00, bus_factor 0.17, issues 0.00, scorecard 0.00 |
| pypi/pyutilib@6.0.0 | ailing | no | 65.1 | r2 | staleness 0.39, maintenance 0.31, bus_factor 0.15, issues 0.06, scorecard 0.09 |
| pypi/rmextract@0.5.1 | dead | yes | 60.1 | r4 | staleness 0.38, maintenance 0.33, bus_factor 0.17, issues 0.00, scorecard 0.12 |
| pypi/robotframework-angularjs@1.0.0 | finished-healthy | no | 75.8 | r2 | staleness 0.81, maintenance 0.00, bus_factor 0.19, issues 0.00, scorecard 0.00 |
| pypi/sklearn@0.0.post12 | dead | yes | 97.6 | r2 | staleness 1.00, maintenance 0.00, bus_factor 0.00, issues 0.00, scorecard 0.00 |
| pypi/zilch@0.1.3 | finished-healthy | no | 97.9 | r2 | staleness 0.51, maintenance 0.20, bus_factor 0.10, issues 0.10, scorecard 0.08 |

## Row details

### npm/animate-components@1.4.8

- label: ailing; predicted: dead; evidence kind: maintainer_statement
- dead_reason: score; mortality: 88.5; pre-S1 mortality: 88.5; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.850 | 0.100 | 0.100 | 8.50 |

| raw | value |
|---|---|
| s2_age_months | 109.5 |
| s3_age_months | 101.8 |
| s4 | 0 |
| s8 | 1.5 |
| s5_committers | 0 |
| s6_open | 5 |
| s6_closed | 17 |
| s9_weekly_downloads | 166 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/graphql-list-fields@2.0.4

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 61.7; pre-S1 mortality: 61.7; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.879 | 0.250 | 0.250 | 21.96 |
| r3 | yes | 0.117 | 0.250 | 0.250 | 2.93 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.680 | 0.100 | 0.100 | 6.80 |

| raw | value |
|---|---|
| s2_age_months | 33.1 |
| s3_age_months | 14.8 |
| s4 | 0 |
| s8 | 3.2 |
| s5_committers | 0 |
| s6_open | 0 |
| s6_closed | 11 |
| s9_weekly_downloads | 81538 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/karma@6.4.4

- label: dead; predicted: finished-healthy; evidence kind: maintainer_statement
- dead_reason: -; mortality: 51.6; pre-S1 mortality: 51.6; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.646 | 0.250 | 0.250 | 16.14 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.550 | 0.100 | 0.100 | 5.50 |

| raw | value |
|---|---|
| s2_age_months | 27.5 |
| s3_age_months | 5.1 |
| s4 | 0 |
| s8 | 4.5 |
| s5_committers | 0 |
| s6_open | 351 |
| s6_closed | 1714 |
| s9_weekly_downloads | 3642501 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/material-design-lite@1.3.0

- label: ailing; predicted: dead; evidence kind: maintainer_statement
- dead_reason: score; mortality: 60.4; pre-S1 mortality: 60.4; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.540 | 0.100 | 0.100 | 5.40 |

| raw | value |
|---|---|
| s2_age_months | 118.7 |
| s3_age_months | 6.4 |
| s4 | 0 |
| s8 | 4.6 |
| s5_committers | 1 |
| s6_open | 390 |
| s6_closed | 1814 |
| s9_weekly_downloads | 85952 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/pdfjs@2.5.4

- label: ailing; predicted: finished-healthy; evidence kind: maintainer_statement
- dead_reason: -; mortality: 46.3; pre-S1 mortality: 46.3; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.184 | 0.250 | 0.250 | 4.61 |
| r3 | yes | 0.184 | 0.250 | 0.250 | 4.61 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.710 | 0.100 | 0.100 | 7.10 |

| raw | value |
|---|---|
| s2_age_months | 16.4 |
| s3_age_months | 16.4 |
| s4 | 0 |
| s8 | 2.9 |
| s5_committers | 0 |
| s6_open | 69 |
| s6_closed | 160 |
| s9_weekly_downloads | 138640 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/please-upgrade-node@3.2.0

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 63.0; pre-S1 mortality: 63.0; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.800 | 0.100 | 0.100 | 8.00 |

| raw | value |
|---|---|
| s2_age_months | 87.2 |
| s3_age_months | 8.5 |
| s4 | 0 |
| s8 | 2 |
| s5_committers | 0 |
| s6_open | 5 |
| s6_closed | 6 |
| s9_weekly_downloads | 5504139 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/react-accessible-details@3.0.5

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 100.0; pre-S1 mortality: 100.0; S1 override applied: no
- confidence: 0.25 (low); cursed: no; wounded: no; unverified: -
- missing: s3_last_push_at (no_repo), s4_maintained (no_repo), s5_committers (no_repo), s6_open_issues (no_repo), s6_closed_issues (no_repo), s8_overall (no_repo)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 1.000 | 100.00 |
| r3 | no | - | 0.250 | - | - |
| r4 | no | - | 0.200 | - | - |
| r5 | no | - | 0.100 | - | - |
| r6 | no | - | 0.100 | - | - |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 83.1 |
| s3_age_months | - |
| s4 | - |
| s8 | - |
| s5_committers | - |
| s6_open | - |
| s6_closed | - |
| s9_weekly_downloads | 24 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=- |

### npm/react-native-version-check@3.5.0

- label: ailing; predicted: finished-healthy; evidence kind: maintainer_statement
- dead_reason: -; mortality: 43.0; pre-S1 mortality: 43.0; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.267 | 0.250 | 0.250 | 6.66 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.630 | 0.100 | 0.100 | 6.30 |

| raw | value |
|---|---|
| s2_age_months | 18.4 |
| s3_age_months | 9.7 |
| s4 | 0 |
| s8 | 3.7 |
| s5_committers | 0 |
| s6_open | 42 |
| s6_closed | 93 |
| s9_weekly_downloads | 95024 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/rx-sandbox@2.0.5

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 86.8; pre-S1 mortality: 86.8; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.680 | 0.100 | 0.100 | 6.80 |

| raw | value |
|---|---|
| s2_age_months | 39.7 |
| s3_age_months | 36.8 |
| s4 | 0 |
| s8 | 3.2 |
| s5_committers | 0 |
| s6_open | 1 |
| s6_closed | 34 |
| s9_weekly_downloads | 4423 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/serializr@3.0.5

- label: ailing; predicted: finished-healthy; evidence kind: maintainer_statement
- dead_reason: -; mortality: 50.7; pre-S1 mortality: 50.7; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.275 | 0.250 | 0.250 | 6.87 |
| r3 | yes | 0.275 | 0.250 | 0.250 | 6.87 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.700 | 0.100 | 0.100 | 7.00 |

| raw | value |
|---|---|
| s2_age_months | 18.6 |
| s3_age_months | 18.6 |
| s4 | 0 |
| s8 | 3 |
| s5_committers | 0 |
| s6_open | 34 |
| s6_closed | 83 |
| s9_weekly_downloads | 31509 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/smells-code-analyzer@0.1.1

- label: dead; predicted: alive; evidence kind: deprecation_notice
- dead_reason: -; mortality: 16.3; pre-S1 mortality: 16.3; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: -
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.039 | 0.250 | 0.357 | 1.41 |
| r3 | yes | 0.017 | 0.250 | 0.357 | 0.62 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 12.9 |
| s3_age_months | 12.4 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 0 |
| s6_closed | 0 |
| s9_weekly_downloads | 11 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/stwui@0.21.2-next

- label: finished-healthy; predicted: ailing; evidence kind: feature_complete_readme
- dead_reason: -; mortality: 47.1; pre-S1 mortality: 47.1; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: scorecard
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.918 | 0.250 | 0.357 | 32.79 |
| r3 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 34.0 |
| s3_age_months | 3.3 |
| s4 | - |
| s8 | - |
| s5_committers | 1 |
| s6_open | 11 |
| s6_closed | 80 |
| s9_weekly_downloads | 55 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/susy-sass@2.4.0

- label: finished-healthy; predicted: alive; evidence kind: feature_complete_readme
- dead_reason: -; mortality: 14.3; pre-S1 mortality: 14.3; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: -
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r3 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 2.4 |
| s3_age_months | 2.4 |
| s4 | - |
| s8 | - |
| s5_committers | 1 |
| s6_open | 0 |
| s6_closed | 1 |
| s9_weekly_downloads | 6 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/updeep@1.2.4

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 88.0; pre-S1 mortality: 88.0; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.800 | 0.100 | 0.100 | 8.00 |

| raw | value |
|---|---|
| s2_age_months | 44.7 |
| s3_age_months | 44.7 |
| s4 | 0 |
| s8 | 2 |
| s5_committers | 0 |
| s6_open | 0 |
| s6_closed | 56 |
| s9_weekly_downloads | 17175 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/vue-formly@2.5.9

- label: ailing; predicted: dead; evidence kind: maintainer_statement
- dead_reason: score; mortality: 87.9; pre-S1 mortality: 87.9; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.790 | 0.100 | 0.100 | 7.90 |

| raw | value |
|---|---|
| s2_age_months | 75.4 |
| s3_age_months | 46.0 |
| s4 | 0 |
| s8 | 2.1 |
| s5_committers | 0 |
| s6_open | 3 |
| s6_closed | 26 |
| s9_weekly_downloads | 139 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### npm/xmldom@0.6.0

- label: dead; predicted: alive; evidence kind: maintainer_statement
- dead_reason: -; mortality: 27.4; pre-S1 mortality: 27.4; S1 override applied: no
- confidence: 1.00 (full); cursed: yes; wounded: yes; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 0.000 | 0.200 | 0.200 | 0.00 |
| r5 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.240 | 0.100 | 0.100 | 2.40 |

| raw | value |
|---|---|
| s2_age_months | 66.9 |
| s3_age_months | 0.1 |
| s4 | 10 |
| s8 | 7.6 |
| s5_committers | 7 |
| s6_open | 40 |
| s6_closed | 159 |
| s9_weekly_downloads | 1603567 |
| advisories | 16 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=no, repo_archived=no |

### pypi/ansible-bender@0.10.1

- label: ailing; predicted: dead; evidence kind: maintainer_statement
- dead_reason: score; mortality: 60.0; pre-S1 mortality: 60.0; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.500 | 0.100 | 0.100 | 5.00 |

| raw | value |
|---|---|
| s2_age_months | 45.2 |
| s3_age_months | 10.2 |
| s4 | 0 |
| s8 | 5 |
| s5_committers | 0 |
| s6_open | 40 |
| s6_closed | 111 |
| s9_weekly_downloads | 1200 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/auto-resizing-text-edit@0.1.0

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 100.0; pre-S1 mortality: 100.0; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: scorecard
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.357 | 35.71 |
| r3 | yes | 1.000 | 0.250 | 0.357 | 35.71 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 158.6 |
| s3_age_months | 158.6 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 4 |
| s6_closed | 0 |
| s9_weekly_downloads | 6 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/django-context-decorator@1.6.1

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 80.5; pre-S1 mortality: 80.5; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.843 | 0.250 | 0.250 | 21.07 |
| r3 | yes | 0.843 | 0.250 | 0.250 | 21.07 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.840 | 0.100 | 0.100 | 8.40 |

| raw | value |
|---|---|
| s2_age_months | 32.2 |
| s3_age_months | 32.2 |
| s4 | 0 |
| s8 | 1.6 |
| s5_committers | 0 |
| s6_open | 0 |
| s6_closed | 2 |
| s9_weekly_downloads | 9495 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/eventlet@0.41.3

- label: ailing; predicted: alive; evidence kind: maintainer_statement
- dead_reason: -; mortality: 12.0; pre-S1 mortality: 12.0; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 0.400 | 0.200 | 0.200 | 8.00 |
| r5 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.400 | 0.100 | 0.100 | 4.00 |

| raw | value |
|---|---|
| s2_age_months | 0.8 |
| s3_age_months | 0.1 |
| s4 | 6 |
| s8 | 6 |
| s5_committers | 7 |
| s6_open | 192 |
| s6_closed | 399 |
| s9_weekly_downloads | 448015 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/flask-script@2.0.6

- label: ailing; predicted: dead; evidence kind: maintainer_statement
- dead_reason: declared; mortality: 90.0; pre-S1 mortality: 87.8; S1 override applied: yes
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.780 | 0.100 | 0.100 | 7.80 |

| raw | value |
|---|---|
| s2_age_months | 110.2 |
| s3_age_months | 80.2 |
| s4 | 0 |
| s8 | 2.2 |
| s5_committers | 0 |
| s6_open | 27 |
| s6_closed | 84 |
| s9_weekly_downloads | 75886 |
| advisories | 0 (0 with fix) |
| s1_declared | yes |
| s1_parts | registry_deprecated=-, repo_archived=yes |

### pypi/fortls@3.2.2

- label: ailing; predicted: alive; evidence kind: maintainer_statement
- dead_reason: -; mortality: 11.8; pre-S1 mortality: 11.8; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: -
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.331 | 0.250 | 0.357 | 11.82 |
| r3 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 19.9 |
| s3_age_months | 0.4 |
| s4 | - |
| s8 | - |
| s5_committers | 10 |
| s6_open | 55 |
| s6_closed | 139 |
| s9_weekly_downloads | 5255 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/maccarone@0.1.9

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 100.0; pre-S1 mortality: 100.0; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: scorecard
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.357 | 35.71 |
| r3 | yes | 1.000 | 0.250 | 0.357 | 35.71 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 38.7 |
| s3_age_months | 37.3 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 2 |
| s6_closed | 0 |
| s9_weekly_downloads | 6 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/mapdamage@2.2.3

- label: ailing; predicted: alive; evidence kind: maintainer_statement
- dead_reason: -; mortality: 26.2; pre-S1 mortality: 26.2; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: -
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.168 | 0.250 | 0.357 | 6.00 |
| r3 | yes | 0.167 | 0.250 | 0.357 | 5.95 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 16.0 |
| s3_age_months | 16.0 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 1 |
| s6_closed | 55 |
| s9_weekly_downloads | 32 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/mkdocs-multirepo-plugin@0.8.3

- label: ailing; predicted: finished-healthy; evidence kind: maintainer_statement
- dead_reason: -; mortality: 37.3; pre-S1 mortality: 37.3; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: -
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.625 | 0.250 | 0.357 | 22.33 |
| r3 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.051 | 0.100 | 0.143 | 0.73 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 27.0 |
| s3_age_months | 7.9 |
| s4 | - |
| s8 | - |
| s5_committers | 1 |
| s6_open | 62 |
| s6_closed | 56 |
| s9_weekly_downloads | 16387 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/opentaxii@0.9.3

- label: finished-healthy; predicted: ailing; evidence kind: feature_complete_readme
- dead_reason: -; mortality: 57.2; pre-S1 mortality: 57.2; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 0.600 | 0.100 | 0.100 | 6.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.620 | 0.100 | 0.100 | 6.20 |

| raw | value |
|---|---|
| s2_age_months | 49.1 |
| s3_age_months | 8.1 |
| s4 | 0 |
| s8 | 3.8 |
| s5_committers | 2 |
| s6_open | 8 |
| s6_closed | 138 |
| s9_weekly_downloads | 160 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/pandoc-mustache@0.1.0

- label: ailing; predicted: dead; evidence kind: maintainer_statement
- dead_reason: score; mortality: 73.1; pre-S1 mortality: 73.1; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.436 | 0.250 | 0.250 | 10.91 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.720 | 0.100 | 0.100 | 7.20 |

| raw | value |
|---|---|
| s2_age_months | 90.1 |
| s3_age_months | 22.5 |
| s4 | 0 |
| s8 | 2.8 |
| s5_committers | 0 |
| s6_open | 5 |
| s6_closed | 5 |
| s9_weekly_downloads | 223 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/products-zopetree@3.4.0

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 61.3; pre-S1 mortality: 61.3; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.630 | 0.100 | 0.100 | 6.30 |

| raw | value |
|---|---|
| s2_age_months | 47.7 |
| s3_age_months | 0.4 |
| s4 | 0 |
| s8 | 3.7 |
| s5_committers | 0 |
| s6_open | 0 |
| s6_closed | 6 |
| s9_weekly_downloads | 8 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/pydora@2.3.2

- label: finished-healthy; predicted: ailing; evidence kind: feature_complete_readme
- dead_reason: -; mortality: 36.9; pre-S1 mortality: 36.9; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.690 | 0.100 | 0.100 | 6.90 |

| raw | value |
|---|---|
| s2_age_months | 0.0 |
| s3_age_months | 0.0 |
| s4 | 0 |
| s8 | 3.1 |
| s5_committers | 1 |
| s6_open | 0 |
| s6_closed | 45 |
| s9_weekly_downloads | 621 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/pysoundanalyser@0.3.7

- label: dead; predicted: ailing; evidence kind: maintainer_statement
- dead_reason: -; mortality: 59.4; pre-S1 mortality: 59.4; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: scorecard
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.766 | 0.250 | 0.357 | 27.37 |
| r3 | yes | 0.158 | 0.250 | 0.357 | 5.66 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.846 | 0.100 | 0.143 | 12.09 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 30.4 |
| s3_age_months | 15.8 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 12 |
| s6_closed | 1 |
| s9_weekly_downloads | 3 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/pyutilib@6.0.0

- label: ailing; predicted: dead; evidence kind: maintainer_statement
- dead_reason: score; mortality: 65.1; pre-S1 mortality: 65.1; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 0.022 | 0.250 | 0.250 | 0.54 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 0.381 | 0.100 | 0.100 | 3.81 |
| r8 | yes | 0.580 | 0.100 | 0.100 | 5.80 |

| raw | value |
|---|---|
| s2_age_months | 76.8 |
| s3_age_months | 12.5 |
| s4 | 0 |
| s8 | 4.2 |
| s5_committers | 0 |
| s6_open | 29 |
| s6_closed | 13 |
| s9_weekly_downloads | 4433 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/rai-workflow-manager@0.0.52

- label: dead; predicted: alive; evidence kind: maintainer_statement
- dead_reason: -; mortality: 27.7; pre-S1 mortality: 27.7; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: -
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.376 | 0.250 | 0.357 | 13.43 |
| r3 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 21.0 |
| s3_age_months | 7.6 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 0 |
| s6_closed | 0 |
| s9_weekly_downloads | 67 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/robotframework-angularjs@1.0.0

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 75.8; pre-S1 mortality: 75.8; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: scorecard
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.861 | 0.250 | 0.357 | 30.74 |
| r3 | yes | 0.861 | 0.250 | 0.357 | 30.74 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 32.7 |
| s3_age_months | 32.7 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 4 |
| s6_closed | 18 |
| s9_weekly_downloads | 1042 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/torf@4.3.1

- label: finished-healthy; predicted: ailing; evidence kind: feature_complete_readme
- dead_reason: -; mortality: 31.7; pre-S1 mortality: 31.7; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r3 | yes | 0.000 | 0.250 | 0.250 | 0.00 |
| r4 | yes | 0.900 | 0.200 | 0.200 | 18.00 |
| r5 | yes | 0.600 | 0.100 | 0.100 | 6.00 |
| r6 | yes | 0.000 | 0.100 | 0.100 | 0.00 |
| r8 | yes | 0.770 | 0.100 | 0.100 | 7.70 |

| raw | value |
|---|---|
| s2_age_months | 10.0 |
| s3_age_months | 4.3 |
| s4 | 1 |
| s8 | 2.3 |
| s5_committers | 2 |
| s6_open | 5 |
| s6_closed | 42 |
| s9_weekly_downloads | 4843 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/windows-curses@2.4.2

- label: ailing; predicted: alive; evidence kind: maintainer_statement
- dead_reason: -; mortality: 8.6; pre-S1 mortality: 8.6; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: -
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r3 | yes | 0.000 | 0.250 | 0.357 | 0.00 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 0.600 | 0.100 | 0.143 | 8.57 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 7.5 |
| s3_age_months | 7.5 |
| s4 | - |
| s8 | - |
| s5_committers | 2 |
| s6_open | 20 |
| s6_closed | 27 |
| s9_weekly_downloads | 30100 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/zgw-consumers-oas@1.1.0

- label: finished-healthy; predicted: ailing; evidence kind: feature_complete_readme
- dead_reason: -; mortality: 30.9; pre-S1 mortality: 30.9; S1 override applied: no
- confidence: 0.70 (medium); cursed: no; wounded: no; unverified: scorecard
- missing: s4_maintained (scorecard_404), s8_overall (scorecard_404)

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 0.232 | 0.250 | 0.357 | 8.30 |
| r3 | yes | 0.232 | 0.250 | 0.357 | 8.30 |
| r4 | no | - | 0.200 | - | - |
| r5 | yes | 1.000 | 0.100 | 0.143 | 14.29 |
| r6 | yes | 0.000 | 0.100 | 0.143 | 0.00 |
| r8 | no | - | 0.100 | - | - |

| raw | value |
|---|---|
| s2_age_months | 17.6 |
| s3_age_months | 17.6 |
| s4 | - |
| s8 | - |
| s5_committers | 0 |
| s6_open | 0 |
| s6_closed | 0 |
| s9_weekly_downloads | 940 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

### pypi/zilch@0.1.3

- label: finished-healthy; predicted: dead; evidence kind: feature_complete_readme
- dead_reason: score; mortality: 97.9; pre-S1 mortality: 97.9; S1 override applied: no
- confidence: 1.00 (full); cursed: no; wounded: no; unverified: -
- missing: -

| risk | present | value | weight | effective | contribution |
|---|---|---|---|---|---|
| r2 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r3 | yes | 1.000 | 0.250 | 0.250 | 25.00 |
| r4 | yes | 1.000 | 0.200 | 0.200 | 20.00 |
| r5 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r6 | yes | 1.000 | 0.100 | 0.100 | 10.00 |
| r8 | yes | 0.790 | 0.100 | 0.100 | 7.90 |

| raw | value |
|---|---|
| s2_age_months | 178.0 |
| s3_age_months | 178.0 |
| s4 | 0 |
| s8 | 2.1 |
| s5_committers | 0 |
| s6_open | 1 |
| s6_closed | 0 |
| s9_weekly_downloads | 1 |
| advisories | 0 (0 with fix) |
| s1_declared | no |
| s1_parts | registry_deprecated=-, repo_archived=no |

## Counterfactuals (in-sample)

### staleness_missing

| label \ predicted | dead | finished-healthy | alive | ailing | unknown |
|---|---|---|---|---|---|
| dead | 37 | 0 | 1 | 4 | 3 |
| finished-healthy | 15 | 0 | 0 | 4 | 1 |
| alive | 0 | 2 | 24 | 5 | 0 |
| ailing | 14 | 2 | 3 | 1 | 0 |

### scorecard_missing

| label \ predicted | dead | finished-healthy | alive | ailing | unknown |
|---|---|---|---|---|---|
| dead | 39 | 1 | 2 | 3 | 0 |
| finished-healthy | 8 | 2 | 6 | 4 | 0 |
| alive | 0 | 0 | 31 | 0 | 0 |
| ailing | 4 | 3 | 9 | 4 | 0 |

## Missing causes

| row | signal | cause |
|---|---|---|
| npm/aiwg@2026.11.5 | s4_maintained | scorecard_404 |
| npm/aiwg@2026.11.5 | s8_overall | scorecard_404 |
| npm/grafema@0.4.1 | s4_maintained | scorecard_404 |
| npm/grafema@0.4.1 | s8_overall | scorecard_404 |
| npm/llm-wiki-compiler@1.5.0 | s4_maintained | scorecard_404 |
| npm/llm-wiki-compiler@1.5.0 | s8_overall | scorecard_404 |
| npm/react@19.3.1 | s4_maintained | scorecard_404 |
| npm/react@19.3.1 | s8_overall | scorecard_404 |
| npm/react-accessible-details@3.0.5 | s3_last_push_at | no_repo |
| npm/react-accessible-details@3.0.5 | s4_maintained | no_repo |
| npm/react-accessible-details@3.0.5 | s5_committers | no_repo |
| npm/react-accessible-details@3.0.5 | s6_open_issues | no_repo |
| npm/react-accessible-details@3.0.5 | s6_closed_issues | no_repo |
| npm/react-accessible-details@3.0.5 | s8_overall | no_repo |
| npm/smells-code-analyzer@0.1.1 | s4_maintained | scorecard_404 |
| npm/smells-code-analyzer@0.1.1 | s8_overall | scorecard_404 |
| npm/stwui@0.21.2-next | s4_maintained | scorecard_404 |
| npm/stwui@0.21.2-next | s8_overall | scorecard_404 |
| npm/susy-sass@2.4.0 | s4_maintained | scorecard_404 |
| npm/susy-sass@2.4.0 | s8_overall | scorecard_404 |
| pypi/auto-resizing-text-edit@0.1.0 | s4_maintained | scorecard_404 |
| pypi/auto-resizing-text-edit@0.1.0 | s8_overall | scorecard_404 |
| pypi/fastapi@0.162.7 | s4_maintained | scorecard_404 |
| pypi/fastapi@0.162.7 | s8_overall | scorecard_404 |
| pypi/fortls@3.2.2 | s4_maintained | scorecard_404 |
| pypi/fortls@3.2.2 | s8_overall | scorecard_404 |
| pypi/jdxi-editor@0.9.9 | s4_maintained | scorecard_404 |
| pypi/jdxi-editor@0.9.9 | s8_overall | scorecard_404 |
| pypi/kotti-image-gallery@0.3.2 | s4_maintained | scorecard_404 |
| pypi/kotti-image-gallery@0.3.2 | s8_overall | scorecard_404 |
| pypi/maccarone@0.1.9 | s4_maintained | scorecard_404 |
| pypi/maccarone@0.1.9 | s8_overall | scorecard_404 |
| pypi/mapdamage@2.2.3 | s4_maintained | scorecard_404 |
| pypi/mapdamage@2.2.3 | s8_overall | scorecard_404 |
| pypi/mkdocs-multirepo-plugin@0.8.3 | s4_maintained | scorecard_404 |
| pypi/mkdocs-multirepo-plugin@0.8.3 | s8_overall | scorecard_404 |
| pypi/oirfile@2026.10.22 | s4_maintained | scorecard_404 |
| pypi/oirfile@2026.10.22 | s8_overall | scorecard_404 |
| pypi/oximedia@0.2.0 | s4_maintained | scorecard_404 |
| pypi/oximedia@0.2.0 | s8_overall | scorecard_404 |
| pypi/pathlib@1.0.1 | s3_last_push_at | no_repo |
| pypi/pathlib@1.0.1 | s4_maintained | no_repo |
| pypi/pathlib@1.0.1 | s5_committers | no_repo |
| pypi/pathlib@1.0.1 | s6_open_issues | no_repo |
| pypi/pathlib@1.0.1 | s6_closed_issues | no_repo |
| pypi/pathlib@1.0.1 | s8_overall | no_repo |
| pypi/ply@3.11 | s3_last_push_at | no_repo |
| pypi/ply@3.11 | s4_maintained | no_repo |
| pypi/ply@3.11 | s5_committers | no_repo |
| pypi/ply@3.11 | s6_open_issues | no_repo |
| pypi/ply@3.11 | s6_closed_issues | no_repo |
| pypi/ply@3.11 | s8_overall | no_repo |
| pypi/py-d3@0.3.0 | s4_maintained | scorecard_404 |
| pypi/py-d3@0.3.0 | s8_overall | scorecard_404 |
| pypi/pysoundanalyser@0.3.7 | s4_maintained | scorecard_404 |
| pypi/pysoundanalyser@0.3.7 | s8_overall | scorecard_404 |
| pypi/rai-workflow-manager@0.0.52 | s4_maintained | scorecard_404 |
| pypi/rai-workflow-manager@0.0.52 | s8_overall | scorecard_404 |
| pypi/robotframework-angularjs@1.0.0 | s4_maintained | scorecard_404 |
| pypi/robotframework-angularjs@1.0.0 | s8_overall | scorecard_404 |
| pypi/sklearn@0.0.post12 | s3_last_push_at | no_repo |
| pypi/sklearn@0.0.post12 | s4_maintained | no_repo |
| pypi/sklearn@0.0.post12 | s5_committers | no_repo |
| pypi/sklearn@0.0.post12 | s6_open_issues | no_repo |
| pypi/sklearn@0.0.post12 | s6_closed_issues | no_repo |
| pypi/sklearn@0.0.post12 | s8_overall | no_repo |
| pypi/vizro@1.0.0 | s4_maintained | scorecard_404 |
| pypi/vizro@1.0.0 | s8_overall | scorecard_404 |
| pypi/windows-curses@2.4.2 | s4_maintained | scorecard_404 |
| pypi/windows-curses@2.4.2 | s8_overall | scorecard_404 |
| pypi/zgw-consumers-oas@1.1.0 | s4_maintained | scorecard_404 |
| pypi/zgw-consumers-oas@1.1.0 | s8_overall | scorecard_404 |
