"""T859: freeze the original fingerprint bytes and rejection contract."""

import ast
import importlib
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

LEGACY = "bisheng.knowledge.application.unification_inventory_codec"
DOMAIN = "bisheng.knowledge.domain.services.unification_fingerprints"


class Label(Enum):
    VALUE = "毕昇"


class Number(Enum):
    VALUE = 2


SUCCESS = [
    ("null", None, "null"),
    ("true", True, "true"),
    ("false", False, "false"),
    ("integer", 1, "1"),
    ("float", 1.0, "1.0"),
    ("negative_zero", -0.0, "-0.0"),
    ("unicode", "毕昇é", '"毕昇é"'),
    ("controls", 'a"b\\c\n', r'"a\"b\\c\n"'),
    ("ordered_mapping", {"z": 0, "a": False, "空": None}, '{"a":false,"z":0,"空":null}'),
    ("integer_key", {1: "value"}, '{"1":"value"}'),
    ("tuple_order", (2, 1), "[2,1]"),
    ("set_order", {2, 1}, "[1,2]"),
    ("frozenset_order", frozenset({"b", "a"}), '["a","b"]'),
    ("datetime", datetime(2026, 11, 7, 3, 4, 5, 123456), '"2026-11-07T03:04:05.123456"'),
    ("aware_datetime", datetime(2026, 11, 7, 3, 4, 5, tzinfo=UTC), '"2026-11-07T03:04:05+00:00"'),
    ("string_enum", Label.VALUE, '"毕昇"'),
    ("number_enum", Number.VALUE, "2"),
    ("nested", {"b": (2, {"z": None, "a": []}), "a": {}}, '{"a":{},"b":[2,{"a":[],"z":null}]}'),
]
# Filled from the actual legacy functions before moving their definitions.
GOLDEN = {
    "aware_datetime": "a0451d54f85d04f0f635daacb172b5d7105c1b4c748ca4aaeed3cd6759dd2243",
    "controls": "bc66ad49348b837dbb56a89b331dfa7f2bb8e89af2cbe0983d0e72846b2dbff3",
    "datetime": "18a9c8940e6a74338845dd33f17487dad39676b616d2be83c9a044ae65e4d6ab",
    "false": "fcbcf165908dd18a9e49f7ff27810176db8e9f63b4352213741664245224f8aa",
    "float": "d0ff5974b6aa52cf562bea5921840c032a860a91a3512f7fe8f768f6bbe005f6",
    "frozenset_order": "0473ef2dc0d324ab659d3580c1134e9d812035905c4781fdd6d529b0c6860e13",
    "integer": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
    "integer_key": "12b0137f6e4f4cc6df162a759f9ae58d020baa561b9e0fc5d34cf682ccef2699",
    "negative_zero": "c26617c7ccbcaa6631b45d851b8cf56e21d2ca624bdb1193afdbd4b560702cec",
    "nested": "1745a128e5ee35d2caea1c7d17110d9267b2acefda53648365e783c4f7fb922c",
    "null": "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
    "number_enum": "d4735e3a265e16eee03f59718b9b5d03019c07d8b6c51f90da3a666eec13ab35",
    "ordered_mapping": "de267782a0b27462d69c8ffcdc4ccaef2a04033ceff188b590b995ea92b6d386",
    "set_order": "49a64717d5d4cb19952e6eac2946415cf6879adacf9908e7d872332d32c6e684",
    "string_enum": "dc4f95f77012f16f9cf2474c9454ac3702fbc1b761fd043fa936d41aa01db444",
    "true": "b5bea41b6c623f7c09f1bf24dcae58ebab3c0cdd90ad966bc43a45b44867e12b",
    "tuple_order": "af1a1fc110b6094c48582b0ef83553cb7908d7a4365424eef28e76ef6c88d630",
    "unicode": "944d31ccf01f15aa036698369158389d15885dc89c4f0ab30b144f6f6b39f8ad",
}


def cycle():
    value = []
    value.append(value)
    return value


def deep():
    value = []
    for _ in range(2000):
        value = [value]
    return value


REJECTED = {
    "object": object,
    "bytes": lambda: b"raw",
    "date": lambda: date(2026, 11, 7),
    "decimal": lambda: Decimal("1.0"),
    "nan": lambda: float("nan"),
    "positive_infinity": lambda: float("inf"),
    "negative_infinity": lambda: float("-inf"),
    "invalid_unicode": lambda: "\ud800",
    "unordered_mixed_set": lambda: {1, "a"},
    "cycle": cycle,
    "recursion": deep,
}


@pytest.fixture(params=[LEGACY, DOMAIN], ids=["legacy", "domain"])
def functions(request):
    return importlib.import_module(request.param)


@pytest.mark.parametrize("name,value,expected", SUCCESS, ids=[case[0] for case in SUCCESS])
def test_original_success_bytes_and_digests_are_unchanged(functions, name, value, expected):
    assert functions.canonical(value) == expected.encode("utf-8")
    assert functions.digest(value) == GOLDEN[name]


@pytest.mark.parametrize("factory", REJECTED.values(), ids=REJECTED)
def test_original_invalid_values_remain_the_same_domain_error(functions, factory):
    for method in (functions.canonical, functions.digest):
        with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
            method(factory())
        assert failure.value.kwargs == {"reason": "migration_inventory_codec_invalid"}
        assert failure.value.__cause__ is None


def test_private_error_constructor_and_original_exports_are_identical_domain_objects():
    legacy, domain = importlib.import_module(LEGACY), importlib.import_module(DOMAIN)
    for name in ("canonical", "digest", "_invalid"):
        actual = getattr(domain, name)
        assert getattr(legacy, name) is actual and actual.__module__ == DOMAIN
    with pytest.raises(KnowledgeOperationPlanConflictError) as failure:
        domain._invalid()
    assert failure.value.kwargs == {"reason": "migration_inventory_codec_invalid"}


def test_pure_fingerprint_owner_cannot_depend_on_application_core_or_sqlalchemy():
    domain = importlib.import_module(DOMAIN)
    tree = ast.parse(Path(domain.__file__).read_text())
    modules = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else (None,))
    ]
    assert all(".application" not in name and ".core" not in name and "sqlalchemy" not in name for name in modules)
    assert set(modules) <= {"hashlib", "json", "datetime", "enum", "bisheng.common.errcode.knowledge"}
    assert {node.name for node in tree.body if isinstance(node, ast.FunctionDef)} == {"canonical", "digest", "_invalid"}
