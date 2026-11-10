"""Pure response parsers for the autopsy source clients.

Purpose: one module per source that turns an already-decoded JSON value into
validated scalar fields, or ``None``. No I/O, no clock, no logging.

D3: a parser accepts any ``object`` and never raises for malformed data; it
returns ``None`` instead. D4: a field that is absent or invalid is ``None``,
never ``0`` and never a guess. D11: parsers return validated scalars only, so
response text (descriptions, deprecation messages, READMEs) never reaches
evidence, notes or warnings.
"""
