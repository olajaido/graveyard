from core.scan import errors


def test_class_name_equals_code() -> None:
    for code in errors.CODES:
        cls = getattr(errors, code)
        assert cls.__name__ == code
        assert cls().code == code
        assert issubclass(cls, errors.ScanError)


def test_unknown_names_map_to_internal() -> None:
    assert errors.code_for("ValueError") == "INTERNAL"
    assert errors.code_for(None) == "INTERNAL"
    assert errors.code_for("NO_MANIFESTS") == "NO_MANIFESTS"
    assert "SBOM" in errors.title_for("NO_MANIFESTS")
