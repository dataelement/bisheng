"""Guard independent DSH features against error-code and locale-key collisions."""

import json
from pathlib import Path

import pytest

from bisheng.common.errcode import dsh, dsh_audit
from bisheng.common.errcode.base import BaseErrorCode


def test_dsh_error_codes_are_unique():
    seen = {}
    for module in (dsh, dsh_audit):
        for name, cls in vars(module).items():
            if not isinstance(cls, type) or not issubclass(cls, BaseErrorCode) or cls is BaseErrorCode:
                continue
            code = cls.Code
            assert code not in seen, f"{name} and {seen.get(code)} share {code}"
            seen[code] = name


@pytest.mark.parametrize("language", ["en", "ja", "zh-Hans"])
def test_dsh_locales_have_unique_keys_and_cover_both_features(language):
    root = Path(__file__).resolve().parents[4]
    source = root / "src/frontend/packages/locales/src/api_errors" / f"{language}.json"

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate locale key: {key}"
            result[key] = value
        return result

    translations = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    for module in (dsh, dsh_audit):
        for cls in vars(module).values():
            if isinstance(cls, type) and issubclass(cls, BaseErrorCode) and cls is not BaseErrorCode:
                assert str(cls.Code) in translations
