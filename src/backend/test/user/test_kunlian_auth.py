"""T037 覆盖 AC-01, AC-02, AC-08, AC-11, AC-14, AC-17, AC-25。"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError
from bisheng.user.domain.models.user import UserLogin
from bisheng.user.domain.services.auth import AuthJwt, LoginUser
from bisheng.user.domain.services.user import UserService

REFERENCE = "fixture-session-reference-with-32-chars"


@pytest.fixture
def signer():
    result = AuthJwt.__new__(AuthJwt)
    result.jwt_secret = "fixture-HS256-secret-at-least-32-characters"
    result.cookie_conf = SimpleNamespace(jwt_iss="fixture-bisheng", jwt_token_expire_time=3600)
    result._encode_algorithm = "HS256"
    result._decode_algorithms = ["HS256"]
    return result


def user(source="kunlian"):
    return SimpleNamespace(
        user_id=17, user_name="自然人", source=source, token_version=3, delete=0, password="reset-password"
    )


def claims(signer, token):
    return jwt.decode(token, signer.jwt_secret, issuer=signer.cookie_conf.jwt_iss, algorithms=["HS256"])


async def test_fixed_issue_context_is_replayed_without_extending_expiry(signer, monkeypatch):
    from bisheng.user.domain.services import auth as module

    now = int(datetime.now(UTC).timestamp())
    kwargs = {
        "tenant_id": 7,
        "auth_source": "kunlian",
        "kunlian_session": REFERENCE,
        "issued_at": now - 10,
        "absolute_expires_at": now + 120,
    }
    first = LoginUser.create_access_token(user(), signer, **kwargs)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(now + 20, tz=tz)

    monkeypatch.setattr(module, "datetime", Later)
    second = LoginUser.create_access_token(user(), signer, **kwargs)
    assert first == second
    payload = claims(signer, second)
    assert payload["iat"] == now - 10 and payload["exp"] == now + 120
    subject = json.loads(payload["sub"])
    assert subject == {
        "user_id": 17,
        "user_name": "自然人",
        "tenant_id": 7,
        "token_version": 3,
        "auth_source": "kunlian",
        "kunlian_session": REFERENCE,
    }
    assert "access_token" not in subject and "id_token" not in subject


@pytest.mark.parametrize("case", ["no_context", "no_reference", "no_source", "local_user"])
def test_reserved_signing_cannot_fall_back_to_ordinary_token(signer, case):
    now = int(datetime.now(UTC).timestamp())
    kwargs = {
        "tenant_id": 7,
        "auth_source": "kunlian",
        "kunlian_session": REFERENCE,
        "issued_at": now,
        "absolute_expires_at": now + 120,
    }
    target = user()
    if case == "no_context":
        kwargs = {"tenant_id": 7}
    elif case == "no_reference":
        del kwargs["kunlian_session"]
    elif case == "no_source":
        del kwargs["auth_source"]
    else:
        target = user("local")
    with pytest.raises(KunlianTrustRejectedError):
        LoginUser.create_access_token(target, signer, **kwargs)


@pytest.mark.parametrize(
    "markers",
    [
        {"auth_source": "kunlian"},
        {"kunlian_session": REFERENCE},
        {"auth_source": "local", "kunlian_session": REFERENCE},
        {"auth_source": "kunlian", "kunlian_session": ""},
    ],
)
def test_incomplete_signed_markers_are_rejected_before_ordinary_subject_fallback(signer, markers):
    subject = {"user_id": 17, "user_name": "自然人", "tenant_id": 7, "token_version": 3, **markers}
    token = jwt.encode(
        {"sub": json.dumps(subject), "iss": "fixture-bisheng", "exp": int(datetime.now(UTC).timestamp()) + 60},
        signer.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(KunlianTrustRejectedError):
        signer.decode_jwt_token(token)


def test_local_token_default_and_explicit_duration_stay_unchanged(signer):
    before = int(datetime.now(UTC).timestamp())
    token = LoginUser.create_access_token(user("local"), signer, tenant_id=7)
    payload = claims(signer, token)
    assert "iat" not in payload and payload["exp"] >= before + 3600
    assert set(json.loads(payload["sub"])) == {"user_id", "user_name", "tenant_id", "token_version"}
    short = signer.create_access_token({"user_id": 17}, expires_in=17)
    assert before + 17 <= claims(signer, short)["exp"] <= int(datetime.now(UTC).timestamp()) + 17


@pytest.mark.parametrize("reset_password", [False, True])
async def test_reserved_user_cannot_password_login_even_after_password_reset(monkeypatch, reset_password):
    from bisheng.common.errcode.user import UserValidateError
    from bisheng.user.domain.services import user as module

    target = user()
    target.password = "reset-password" if reset_password else ""
    monkeypatch.setattr(module, "settings", SimpleNamespace(aget_from_db=AsyncMock(return_value=False)))
    monkeypatch.setattr(module.UserDao, "aget_login_candidates_by_account", AsyncMock(return_value=[target]))
    monkeypatch.setattr(module.UserDao, "aexists_disabled_login_account", AsyncMock(return_value=False))
    decrypt = MagicMock(side_effect=AssertionError("reserved account reached password decryption"))
    monkeypatch.setattr(UserService, "decrypt_md5_password", decrypt)
    check = AsyncMock()
    monkeypatch.setattr(UserService, "judge_user_password", check)
    result = await UserService.user_login(
        SimpleNamespace(), UserLogin(user_name="自然人", password="fixture"), auth_jwt=MagicMock()
    )
    assert result.status_code == UserValidateError.Code
    decrypt.assert_not_called()
    check.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["expired", "too_long", "missing_time", "external_credential"])
def test_fixed_context_cannot_extend_hard_deadline_or_embed_external_credentials(signer, invalid):
    now = int(datetime.now(UTC).timestamp())
    subject = {
        "user_id": 17,
        "user_name": "自然人",
        "tenant_id": 7,
        "token_version": 3,
        "auth_source": "kunlian",
        "kunlian_session": REFERENCE,
    }
    issued, expiry = now, now + 120
    if invalid == "expired":
        issued, expiry = now - 100, now - 1
    elif invalid == "too_long":
        expiry = now + 28801
    elif invalid == "missing_time":
        issued = expiry = None
    else:
        subject["access_token"] = "fixture-private-AT"
    with pytest.raises(KunlianTrustRejectedError):
        signer.create_access_token(subject, issued_at=issued, absolute_expires_at=expiry)
