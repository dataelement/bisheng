"""Side-effect-free, scoped YAML/env loading shared by runtime and tooling."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger

from bisheng.core.config.secret_crypto import CredentialConfigurationError, get_keyring


@dataclass(frozen=True)
class EnvReference:
    name: str


@dataclass(repr=False)
class ConfigDocument:
    data: dict = field(repr=False)
    raw: dict = field(repr=False)
    sources: dict[tuple[str, ...], str] = field(default_factory=dict)


class _ConfigLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        literal = [key.value for key, _ in node.value if key.tag == "tag:yaml.org,2002:str"]
        if len(set(literal)) != len(literal):
            raise ValueError("duplicate configuration field")
        return super().construct_mapping(node, deep=deep)


def _env_reference(loader, node):
    value = loader.construct_scalar(node)
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value.strip())
    if not match:
        raise ValueError("invalid environment reference")
    return EnvReference(match.group(1))


_ConfigLoader.add_constructor("!env", _env_reference)


class _ConfigDumper(yaml.SafeDumper):
    pass


_ConfigDumper.add_representer(
    EnvReference, lambda dumper, value: dumper.represent_scalar("!env", "${" + value.name + "}")
)


def dump_document(data: dict) -> str:
    return yaml.dump(data, Dumper=_ConfigDumper, allow_unicode=True, sort_keys=False)


def _decode_env(raw: str) -> str:
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return ""
    if raw[0] not in "\"'":
        return re.sub(r"\s+#.*", "", raw)
    quote = raw[0]
    result = []
    i = 1
    while i < len(raw):
        char = raw[i]
        nextchar = raw[i + 1] if i + 1 < len(raw) else ""
        if char == quote:
            tail = raw[i + 1 :].strip()
            if tail and not tail.startswith("#"):
                raise ValueError("invalid dotenv tail")
            return "".join(result)
        if quote == '"' and char == "$" and nextchar == "$":
            result.append("$")
            i += 2
            continue
        if char == "\\" and nextchar == quote:
            result.append(quote)
            i += 2
            continue
        if quote == '"' and char == "\\":
            if nextchar in ("n", "r"):
                raise ValueError("multiline dotenv value")
            result.append({"t": "\t", "\\": "\\"}.get(nextchar, char + nextchar))
            i += 2
            continue
        result.append(char)
        i += 1
    raise ValueError("unterminated dotenv value")


def read_env_file(path: str | Path) -> dict[str, str]:
    result = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        for line in lines:
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
            if not match:
                continue
            name, raw = match.groups()
            if name in result:
                raise ValueError("duplicate dotenv key")
            result[name] = _decode_env(raw)
    except (OSError, UnicodeError, ValueError):
        raise CredentialConfigurationError("env_file: invalid single-line document") from None
    return result


def load_config(
    path: str | Path, environ: Mapping[str, str] | None = None, env_file: str | Path | None = None
) -> ConfigDocument:
    environment = dict(os.environ if environ is None else environ)
    if env_file:
        for name, value in read_env_file(env_file).items():
            if name in environment and environment[name] != value:
                raise CredentialConfigurationError(f"environment.{name}: conflicting sources")
            environment[name] = value
    try:
        raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_ConfigLoader)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError):
        raise CredentialConfigurationError("config: invalid or unreadable YAML") from None
    if not isinstance(raw, dict):
        raise CredentialConfigurationError("config: object required")
    sources = {}
    active = set()

    def resolve(value, location=()):
        if isinstance(value, EnvReference):
            if value.name not in environment:
                raise CredentialConfigurationError(f"environment.{value.name}: required value missing")
            sources[location] = value.name
            return environment[value.name]
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in active:
                raise CredentialConfigurationError("config: cyclic document rejected")
            active.add(identity)
            try:
                if isinstance(value, dict):
                    return {key: resolve(item, (*location, str(key))) for key, item in value.items()}
                return [resolve(item, (*location, str(i))) for i, item in enumerate(value)]
            finally:
                active.remove(identity)
        return value

    data = resolve(raw)
    if not data.get("database_url") and environment.get("bisheng_DATABASE_URL"):
        data["database_url"] = environment["bisheng_DATABASE_URL"]
        sources[("database_url",)] = "bisheng_DATABASE_URL"
    return ConfigDocument(data, raw, sources)


def validate_runtime(data: dict, model_type=None):
    """Validate before service/Alembic imports can open infrastructure clients."""
    from pydantic import ValidationError

    from bisheng.core.config.settings import Settings

    get_keyring()
    if not data.get("database_url") and not os.getenv("bisheng_DATABASE_URL"):
        raise CredentialConfigurationError("database_url: explicit connection required")
    # Same rule as ConfigService.load_settings_from_yaml: an unknown top-level
    # key only warns (by name, never its value) and has no effect. Known fields,
    # including credentials, keep their strict validation below.
    cleaned = {}
    for key, value in data.items():
        if key == "admin":
            continue
        if key not in Settings.model_fields:
            logger.warning("Ignoring unknown top-level config key {!r}; this setting has no effect", key)
            continue
        cleaned[key] = value
    try:
        settings = (model_type or Settings)(**cleaned)
    except ValidationError as error:
        paths = [
            ".".join(map(str, item["loc"])) or "configuration"
            for item in error.errors(include_input=False, include_context=False, include_url=False)
        ]
        raise CredentialConfigurationError("config: invalid fields " + ", ".join(dict.fromkeys(paths))) from None
    except (TypeError, ValueError):
        raise CredentialConfigurationError("config: credential validation failed") from None
    if "object_storage" in data:
        conf = settings.object_storage.minio
        if conf and (not conf.access_key or not conf.secret_key):
            raise CredentialConfigurationError("object_storage.minio: credentials required")
    return settings


def config_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() and "/" not in str(value):
        return Path(__file__).resolve().parents[2] / path
    return path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Read-only runtime configuration preflight")
    parser.add_argument("--config", default=os.getenv("config", "config.yaml"))
    args = parser.parse_args()
    try:
        validate_runtime(load_config(config_path(args.config)).data)
    except CredentialConfigurationError as error:
        print(str(error))
        return 2
    revision = os.getenv("BS_CREDENTIAL_REVISION", "source")
    if revision != "source" and not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", revision):
        print("config: invalid credential revision")
        return 2
    print(f"Configuration preflight passed revision={revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
