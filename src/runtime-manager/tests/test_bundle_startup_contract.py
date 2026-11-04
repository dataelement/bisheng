"""F119 AC-12, AC-13, AC-14, AC-15, AC-16: declared commands and safe language fallbacks."""

import json

import pytest

from runtime_manager.bundle_inputs import BundleInputError, startup_command


@pytest.mark.parametrize(
    "language,entry,binary",
    [
        ("python3.11", "main.py", "python"),
        ("python3.11", "app.py", "python"),
        ("node20", "server.js", "node"),
        ("node20", "index.js", "node"),
        ("node20", "app.js", "node"),
        ("node20", "main.js", "node"),
    ],
)
def test_language_script_entry(tmp_path, language, entry, binary):
    (tmp_path / entry).write_text("")
    assert startup_command(tmp_path, language) == [binary, entry]


def test_precedence_keeps_declared_and_procfile_before_language(tmp_path):
    (tmp_path / "main.py").write_text("")
    (tmp_path / "app.py").write_text("")
    assert startup_command(tmp_path, "python3.11") == ["python", "main.py"]
    (tmp_path / "Procfile").write_text("web: python custom.py\n")
    assert startup_command(tmp_path, "python3.11") == ["/bin/sh", "-c", "python custom.py"]
    assert startup_command(tmp_path, "python3.11", ["custom", "--arg"]) == ["custom", "--arg"]


def test_node_start_script_runs_without_implicit_npm_lifecycle(tmp_path):
    package = {"scripts": {"start": "local-server --port $PORT", "prestart": "must-not-run"}, "main": "missing.js"}
    (tmp_path / "package.json").write_text(json.dumps(package))
    assert startup_command(tmp_path, "node20") == ["/bin/sh", "-c", "local-server --port $PORT"]


@pytest.mark.parametrize("entry", ["entry.js", "./entry.js"])
def test_node_main_precedes_default_files(tmp_path, entry):
    (tmp_path / "package.json").write_text(json.dumps({"main": entry}))
    (tmp_path / "entry.js").write_text("")
    (tmp_path / "server.js").write_text("")
    assert startup_command(tmp_path, "node20") == ["node", "entry.js"]


@pytest.mark.parametrize(
    "package",
    [
        {"main": "../escape.js"},
        {"main": "/absolute.js"},
        {"main": 12},
        {"scripts": {"start": ["node"]}},
        [],
        {"main": "missing.js"},
    ],
)
def test_invalid_package_startup_is_explained(tmp_path, package):
    (tmp_path / "package.json").write_text(json.dumps(package))
    with pytest.raises(BundleInputError):
        startup_command(tmp_path, "node20")


def test_entry_document_symlink_cannot_escape_package(tmp_path):
    external = tmp_path / "external"
    external.write_text("web: outside\n")
    source = tmp_path / "source"
    source.mkdir()
    (source / "Procfile").symlink_to(external)
    with pytest.raises(BundleInputError):
        startup_command(source, "python3.11")


def test_invalid_json_is_an_input_failure(tmp_path):
    (tmp_path / "package.json").write_text("{")
    with pytest.raises(BundleInputError, match="package_json"):
        startup_command(tmp_path, "node20")


def test_no_entry_is_explicit(tmp_path):
    with pytest.raises(BundleInputError, match="startup_command_required"):
        startup_command(tmp_path, "python3.11")
