# Expected labels of the direct dependencies

Each direct dependency of this demo and its label in Graveyard's **development** evaluation set
(`eval/labelled_packages.csv`, the v1 answer key). No package comes from the held-out set (`eval/heldout/`); the test
`backend/tests/unit/test_demo_haunted_house.py` fails if one does.

These are human labels from public evidence, not Graveyard output. They are for checking the first scans by hand and
must not be used to tune the model. Model v2 reports `Dead` only for a declared death (registry deprecation or an
archived repository), so a package labelled `dead` here may come out `Ailing` when Graveyard sees no declaration
(for example PyPI, which exposes no deprecation flag).

Label source file for every row: `eval/labelled_packages.csv`.

| Ecosystem | Package | Version | Where | Label | Evidence kind | Evidence URL |
|-----------|---------|---------|-------|-------|---------------|--------------|
| npm | `axios` | 1.21.1 | dependencies | **alive** | release_notes | https://github.com/axios/axios/releases |
| npm | `coffee-script` | 1.12.7 | dependencies | **dead** | deprecation_notice | https://registry.npmjs.org/coffee-script/latest |
| npm | `command-line-args` | 6.0.2 | dependencies | **finished-healthy** | feature_complete_readme | https://github.com/75lb/command-line-args |
| npm | `commander` | 15.1.0 | dependencies | **alive** | release_notes | https://raw.githubusercontent.com/tj/commander.js/master/CHANGELOG.md |
| npm | `gulp-util` | 3.0.8 | dependencies | **dead** | deprecation_notice | https://registry.npmjs.org/gulp-util/latest |
| npm | `material-design-lite` | 1.3.0 | dependencies | **ailing** | maintainer_statement | https://raw.githubusercontent.com/google/material-design-lite/HEAD/README.md |
| npm | `querystring` | 0.2.1 | dependencies | **dead** | deprecation_notice | https://registry.npmjs.org/querystring/latest |
| npm | `request-promise` | 4.2.6 | dependencies | **dead** | deprecation_notice | https://registry.npmjs.org/request-promise/latest |
| npm | `serializr` | 3.0.5 | dependencies | **ailing** | maintainer_statement | https://raw.githubusercontent.com/mobxjs/serializr/HEAD/README.md |
| npm | `tslint` | 6.1.3 | devDependencies | **dead** | deprecation_notice | https://registry.npmjs.org/tslint/latest |
| pypi | `appdirs` | 1.4.4 | services/worker/requirements.txt | **dead** | deprecation_notice | https://github.com/ActiveState/appdirs |
| pypi | `argparse` | 1.4.0 | services/worker/requirements.txt | **dead** | archived_repo | https://github.com/ThomasWaldmann/argparse |
| pypi | `attrs` | 26.1.0 | services/worker/requirements.txt | **alive** | release_notes | https://www.attrs.org/en/stable/changelog.html |
| pypi | `eventlet` | 0.41.3 | services/worker/requirements.txt | **ailing** | maintainer_statement | https://github.com/eventlet/eventlet |
| pypi | `flask` | 3.1.3 | services/worker/requirements.txt | **alive** | release_notes | https://flask.palletsprojects.com/en/stable/changes/ |
| pypi | `flask-script` | 2.0.6 | services/worker/requirements.txt | **ailing** | maintainer_statement | https://github.com/smurfix/flask-script |
| pypi | `requests` | 2.34.2 | services/worker/requirements.txt | **alive** | release_notes | https://requests.readthedocs.io/en/latest/community/updates/ |
| pypi | `typed-ast` | 1.5.5 | services/worker/requirements.txt | **dead** | maintainer_statement | https://pypi.org/pypi/typed-ast/json |

Totals: 8 dead, 4 ailing, 1 finished-healthy (the eval set's word for quiet but healthy, which Graveyard calls
Resting), 5 alive.

Transitive packages are not labelled. The Node lockfile pulls in two peer dependencies as well: `request` 2.88.2
(through `request-promise`; deprecated on npm) and `typescript` (through `tslint`).
