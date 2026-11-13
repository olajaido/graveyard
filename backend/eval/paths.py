"""Location of the eval data folder, defined once (D11).

Found from ``__file__``, never from the working directory (EV-RUN-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

DEFAULT_DATA_DIR: Final = Path(__file__).resolve().parents[2] / "eval"
