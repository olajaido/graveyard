"""A small checker of a JSON value against a schema of ``openapi.yaml`` (ui-core UI-B-5).

It exists so a response can be compared with the contract without a new dependency. It covers the
parts of JSON Schema that the file uses: ``$ref``, ``allOf``, ``oneOf``, ``type`` (one name or a
list), ``enum``, ``const``, ``required``, ``properties``, ``additionalProperties``, ``items``,
``pattern`` and ``minimum``.

It is stricter than a plain validator in one way, on purpose: an object schema that lists
``properties`` (directly or through ``allOf``) is treated as closed unless ``additionalProperties``
says otherwise. A field that the API returns and the file does not document is therefore an error,
which is what the contract is for.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

SPEC_PATH = Path(__file__).parents[1] / "openapi.yaml"
type Json = Any


def load_spec() -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text())
    return spec


def _resolve(spec: Json, schema: Json) -> Json:
    while isinstance(schema, dict) and "$ref" in schema:
        node: Json = spec
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def _type_ok(name: str, value: Json) -> bool:
    return {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }[name]


def _members(spec: Json, schema: Json) -> list[Json]:
    """The schema and, recursively, the members of its ``allOf``."""
    schema = _resolve(spec, schema)
    out = [schema]
    for part in schema.get("allOf", []) if isinstance(schema, dict) else []:
        out.extend(_members(spec, part))
    return out


def check(spec: Json, schema: Json, value: Json, path: str = "$", closed: bool = True) -> list[str]:
    """The problems of ``value`` against ``schema``; an empty list means it conforms.

    ``closed`` is false for a member of ``allOf``: the closure test runs once, on the composition.
    """
    schema = _resolve(spec, schema)
    if schema is True or schema == {}:
        return []
    problems: list[str] = []
    if "oneOf" in schema:
        branches = [check(spec, branch, value, path) for branch in schema["oneOf"]]
        if not any(not branch for branch in branches):
            return [f"{path}: matches no branch of oneOf ({branches})"]
    for part in schema.get("allOf", []):
        problems.extend(check(spec, part, value, path, closed=False))
    if "const" in schema and value != schema["const"]:
        problems.append(f"{path}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(n, value) for n in names):
            problems.append(f"{path}: {type(value).__name__} is not {names}")
            return problems
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        problems.append(f"{path}: {value!r} does not match {schema['pattern']}")
    below = (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and "minimum" in schema
        and value < schema["minimum"]
    )
    if below:
        problems.append(f"{path}: {value} is below {schema['minimum']}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            problems.extend(check(spec, schema["items"], item, f"{path}[{i}]"))
    if isinstance(value, dict):
        members = _members(spec, schema)
        declared: dict[str, Json] = {}
        for member in members:
            declared.update(member.get("properties", {}))
        for member in members:
            for key in member.get("required", []):
                if key not in value:
                    problems.append(f"{path}: missing required {key!r}")
        extra = schema.get("additionalProperties")
        for key, item in value.items():
            if key in declared:
                problems.extend(check(spec, declared[key], item, f"{path}.{key}"))
            elif isinstance(extra, dict):
                problems.extend(check(spec, extra, item, f"{path}.{key}"))
            elif closed and extra is not True and declared:
                problems.append(f"{path}: undocumented field {key!r}")
    return problems


def check_schema(name: str, value: Json) -> list[str]:
    spec = load_spec()
    return check(spec, {"$ref": f"#/components/schemas/{name}"}, value, name)
