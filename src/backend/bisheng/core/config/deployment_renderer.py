"""Render a private Settings YAML from deployment JSON and projected Secret files.

Runs as a normal image command. ConfigMaps contain data only, never Python
startup patches. No output includes the rendered values or connection URLs.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from urllib.parse import quote

import yaml
from sqlalchemy.engine import URL


def _secret(path):
    try:
        value = Path(path).read_text(encoding="utf-8")
        if len(value.encode()) > 65536 or "\x00" in value:
            raise ValueError()
        return value
    except (OSError, UnicodeError, TypeError):
        raise ValueError("deployment_secret_unavailable") from None


def render_settings(document):
    from bisheng.core.config.settings import encrypt_token

    if not isinstance(document, dict) or not isinstance(document.get("settings"), dict):
        raise ValueError("deployment_settings_invalid")
    result = copy.deepcopy(document["settings"])
    result.pop("admin", None)
    database = document.get("database")
    if database:
        password = _secret(database["password_file"])
        encrypted = encrypt_token(password).decode() if password else None
        result["database_url"] = URL.create(
            database.get("driver", "mysql+pymysql"),
            username=database["username"],
            password=encrypted,
            host=database["host"],
            port=int(database["port"]),
            database=database.get("name"),
            query=database.get("query", {"charset": "utf8mb4"}),
        ).render_as_string(hide_password=False)
    redis = document.get("redis")
    if redis:
        password = _secret(redis["password_file"]) if redis.get("password_file") else ""
        encrypted = encrypt_token(password).decode() if password else ""
        username = quote(redis.get("username", ""), safe="")
        credentials = f"{username}:{encrypted}@" if encrypted else (f"{username}@" if username else "")
        host = redis["host"]
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        scheme = "rediss" if redis.get("tls") else "redis"
        for field, index in (("redis_url", redis["cacheDb"]), ("celery_redis_url", redis["celeryDb"])):
            if type(index) is not int or not 0 <= index <= 15:
                raise ValueError("deployment_redis_index_invalid")
            result[field] = f"{scheme}://{credentials}{host}:{int(redis['port'])}/{index}"
    for binding in document.get("secret_files", []):
        keys = binding.get("path")
        if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not k for k in keys):
            raise ValueError("deployment_secret_binding_invalid")
        cursor = result
        for key in keys[:-1]:
            cursor = cursor.setdefault(key, {})
            if not isinstance(cursor, dict):
                raise ValueError("deployment_secret_binding_conflict")
        value = _secret(binding["file"])
        if binding.get("encoding") == "json":
            value = json.loads(value)
        elif binding.get("encoding", "text") != "text":
            raise ValueError("deployment_secret_encoding_invalid")
        cursor[keys[-1]] = value
    return result


def write_private(path, document):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        if destination.suffix == ".json":
            json.dump(document, stream)
        else:
            yaml.safe_dump(document, stream, allow_unicode=True, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec")
    source.add_argument("--existing")
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-seed")
    args = parser.parse_args()
    try:
        if args.existing:
            raw = Path(args.existing).read_text()
            if not raw or len(raw.encode()) > 4 * 1024 * 1024:
                raise ValueError("existing_configuration_invalid")
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(raw)
        else:
            document = json.loads(Path(args.spec).read_text())
            write_private(args.output, render_settings(document))
        if args.data_seed:
            seed = Path(args.data_seed).read_bytes()
            if len(seed) != 32:
                raise ValueError("deployment_data_seed_invalid")
            write_private(
                Path(args.output).parent / "data-keys.json",
                {"active_key_id": "data_v1", "private_keys": {"data_v1": seed.hex()}},
            )
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit(
            "Deployment configuration rendering failed; check mounted configuration and Secret keys"
        ) from None


if __name__ == "__main__":
    main()
