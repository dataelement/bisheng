"""F119 AC-06 through AC-11: one public environment for every execution adapter."""

import pytest


def environment(**changes):
    from runtime_manager.runtime_environment import platform_environment

    values = {"app_id": "app-a", "slug": "example", "version_id": "version-b", "version_no": 4, "port": 8081}
    return platform_environment(**{**values, **changes})


def test_platform_values_override_extra_without_changing_it():
    original = {"BISHENG_APP_DB_PATH": "/workspace/app/wrong.db", "BUSINESS_VALUE": "value"}
    result = environment(extra=original)
    assert result["BISHENG_APP_DB_PATH"] == "/data/app.db"
    assert result["BISHENG_APP_DB_URL"] == "sqlite:////data/app.db"
    assert result["BISHENG_APP_ID"] == "app-a"
    assert result["BISHENG_APP_SLUG"] == "example"
    assert result["BISHENG_APP_VERSION_ID"] == "version-b"
    assert result["BISHENG_APP_VERSION"] == "4"
    assert result["BISHENG_APP_PORT"] == result["PORT"] == "8081"
    assert result["BUSINESS_VALUE"] == "value"
    assert original["BISHENG_APP_DB_PATH"] == "/workspace/app/wrong.db"


@pytest.mark.parametrize("language", ["python3.11", "node20", "static"])
def test_preview_metadata_uses_actual_prefix_and_keeps_same_container_db_path(language):
    result = environment(language=language, base_path="/apps/example/_preview/session", health_path="/health")
    assert result["BISHENG_APP_BASE_PATH"] == "/apps/example/_preview/session"
    assert result["BISHENG_APP_HEALTH_PATH"] == "/health"
    assert result["BISHENG_APP_DB_PATH"] == "/data/app.db"
    if language == "python3.11":
        assert result["UVICORN_ROOT_PATH"] == result["GRADIO_ROOT_PATH"] == result["BISHENG_APP_BASE_PATH"]
        assert result["STREAMLIT_SERVER_BASE_URL_PATH"] == "apps/example/_preview/session"
    if language == "node20":
        assert result["BASE_PATH"] == result["BISHENG_APP_BASE_PATH"]


def test_probe_does_not_invent_version_number_and_default_prefix_is_stable():
    result = environment(version_no=None)
    assert result["BISHENG_APP_VERSION"] == ""
    assert result["BISHENG_APP_VERSION_ID"] == "version-b"
    assert result["BISHENG_APP_BASE_PATH"] == "/apps/example"


def test_bundle_paths_support_local_binaries_but_full_image_path_is_untouched():
    assert environment(language="node20", bundle=True)["PATH"].split(":").index("/workspace/app/node_modules/.bin") < 2
    assert environment(language="python3.11", bundle=True)["PATH"].startswith("/opt/venv/bin:")
    assert environment(language="custom-image", extra={"PATH": "/custom/bin"})["PATH"] == "/custom/bin"
    assert "PATH" not in environment(language="custom-image")
