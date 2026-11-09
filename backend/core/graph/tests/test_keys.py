"""Package-key builders (DG-DEP-2): npm_key and pypi_key delegate to core.purl."""

import pytest

from core.graph.keys import npm_key, pypi_key


@pytest.mark.parametrize(
    ("name", "version", "expected"),
    [
        ("JSONStream", "1.3.5", "npm/jsonstream@1.3.5"),
        ("@Babel/Core", "7.24.0", "npm/%40babel/core@7.24.0"),
        ("left-pad", "1.3.0", "npm/left-pad@1.3.0"),
    ],
)
def test_npm_key(name: str, version: str, expected: str) -> None:
    assert npm_key(name, version) == expected


@pytest.mark.parametrize(
    ("name", "version", "expected"),
    [
        ("Flask_SQLAlchemy", "3.1.1", "pypi/flask-sqlalchemy@3.1.1"),
        ("zope.interface", "6.0", "pypi/zope-interface@6.0"),
        ("six", "1.17.0", "pypi/six@1.17.0"),
    ],
)
def test_pypi_key(name: str, version: str, expected: str) -> None:
    assert pypi_key(name, version) == expected


@pytest.mark.parametrize(
    "name",
    ["", "@scope", "@scope/", "@/name", "@a/b/c", "a b", "a/b"],
)
def test_npm_key_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError):
        npm_key(name, "1.0.0")


@pytest.mark.parametrize("name", ["", "   ", "!!!", "a/b"])
def test_pypi_key_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError):
        pypi_key(name, "1.0.0")
