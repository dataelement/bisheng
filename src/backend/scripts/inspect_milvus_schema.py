"""Inspect the schema of Milvus collections used by knowledge bases.

Background
----------
Online inserts fail with errors like::

    <DataNotMatchException: (code=1, message=Insert missed an field `abstract`
     to collection without set nullable==true or set default_value)>

while brand-new knowledge spaces work fine. That means an *existing* collection
has a field (e.g. ``abstract``) declared as NOT nullable and WITHOUT a default
value, but the current insert path no longer provides that field. Newly created
collections get the up-to-date schema, so they are unaffected.

This script connects to Milvus using the backend's own configuration and prints
the full field schema of one/many collections, highlighting the exact fields
that would trigger this error (``nullable=False`` and no ``default_value``).

Usage
-----
    # one collection by name
    python scripts/inspect_milvus_schema.py --collection col_xxxx

    # resolve the collection from a knowledge base id
    python scripts/inspect_milvus_schema.py --knowledge-id 123

    # scan every collection on the server
    python scripts/inspect_milvus_schema.py --all

    # only print collections that have a risky (not-nullable, no-default) field
    python scripts/inspect_milvus_schema.py --all --only-risky

    # diff two collections (e.g. a healthy new one vs. a failing old one)
    python scripts/inspect_milvus_schema.py --diff new_col old_col

Run it from ``src/backend`` so the ``bisheng`` package and config are importable.
"""

import argparse
import sys
from typing import Dict, List, Optional

from pymilvus import Collection, DataType, connections, utility

from bisheng.common.services.config_service import settings


def _connect() -> str:
    """Connect to Milvus with the backend connection args. Returns the alias."""
    conf = settings.get_vectors_conf().milvus
    connection_args = dict(conf.connection_args or {})
    if not connection_args:
        raise RuntimeError(
            "No milvus connection_args configured. Check vectorstores.milvus in config.yaml."
        )

    # Mirror MilvusFactory: host/port -> uri
    if connection_args.get("host") and connection_args.get("port"):
        host = connection_args.pop("host")
        port = connection_args.pop("port")
        connection_args["uri"] = f"http://{host}:{port}"

    alias = "schema_inspect"
    safe = {k: v for k, v in connection_args.items() if k not in ("password", "token")}
    print(f"Connecting to Milvus: {safe}")
    connections.connect(alias=alias, **connection_args)
    return alias


def _field_info(field) -> Dict:
    """Normalize a FieldSchema into a plain dict across pymilvus versions."""
    d = field.to_dict()
    return {
        "name": d.get("name"),
        "type": DataType(d["type"]).name if "type" in d else str(d.get("type")),
        "is_primary": d.get("is_primary", False),
        "auto_id": d.get("auto_id", False),
        "nullable": d.get("nullable", False),
        "has_default": "default_value" in d,
        "default_value": d.get("default_value"),
        "params": d.get("params", {}),
    }


def _risky_fields(fields: List[Dict]) -> List[str]:
    """Fields that cause 'Insert missed a field' when not supplied.

    A field is risky if it is NOT nullable, has NO default value, is not the
    auto-id primary key, and is not a system/vector field that the insert path
    always populates.
    """
    risky = []
    for f in fields:
        if f["nullable"] or f["has_default"]:
            continue
        if f["is_primary"] and f["auto_id"]:
            continue
        risky.append(f["name"])
    return risky


def _print_collection(alias: str, name: str, only_risky: bool = False) -> Optional[List[str]]:
    try:
        col = Collection(name=name, using=alias)
        schema = col.schema
    except Exception as e:  # noqa: BLE001
        print(f"\n## {name}\n  !! cannot read schema: {e}")
        return None

    fields = [_field_info(f) for f in schema.fields]
    risky = _risky_fields(fields)

    if only_risky and not risky:
        return risky

    print(f"\n## Collection: {name}")
    print(f"   description: {schema.description!r}")
    print(f"   {'field':<24}{'type':<12}{'pk':<4}{'autoid':<8}{'nullable':<10}{'default'}")
    print(f"   {'-' * 70}")
    for f in fields:
        default = f["default_value"] if f["has_default"] else "-"
        print(
            f"   {f['name']:<24}{f['type']:<12}"
            f"{'Y' if f['is_primary'] else '':<4}"
            f"{'Y' if f['auto_id'] else '':<8}"
            f"{'Y' if f['nullable'] else 'N':<10}"
            f"{default}"
        )

    if risky:
        print(f"   >>> RISKY (not nullable, no default): {', '.join(risky)}")
    return risky


def _diff(alias: str, name_a: str, name_b: str) -> None:
    col_a = {f["name"]: f for f in (_field_info(x) for x in Collection(name_a, using=alias).schema.fields)}
    col_b = {f["name"]: f for f in (_field_info(x) for x in Collection(name_b, using=alias).schema.fields)}

    only_a = sorted(set(col_a) - set(col_b))
    only_b = sorted(set(col_b) - set(col_a))
    common = sorted(set(col_a) & set(col_b))

    print(f"\n## Diff: {name_a}  vs  {name_b}")
    print(f"   only in {name_a}: {only_a or '-'}")
    print(f"   only in {name_b}: {only_b or '-'}")
    for fname in common:
        a, b = col_a[fname], col_b[fname]
        diffs = []
        for key in ("type", "nullable", "has_default", "default_value", "is_primary", "auto_id"):
            if a[key] != b[key]:
                diffs.append(f"{key}: {a[key]} != {b[key]}")
        if diffs:
            print(f"   field {fname}: {'; '.join(diffs)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Milvus collection schemas.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--collection", help="collection name to inspect")
    group.add_argument("--knowledge-id", type=int, help="resolve collection from a knowledge base id")
    group.add_argument("--all", action="store_true", help="scan all collections on the server")
    group.add_argument("--diff", nargs=2, metavar=("COL_A", "COL_B"), help="diff two collections")
    parser.add_argument("--only-risky", action="store_true", help="with --all: only show risky collections")
    args = parser.parse_args()

    alias = _connect()

    if args.diff:
        _diff(alias, args.diff[0], args.diff[1])
        return 0

    if args.collection:
        names = [args.collection]
    elif args.knowledge_id is not None:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        kb = KnowledgeDao.query_by_id(args.knowledge_id)
        if not kb:
            print(f"knowledge id {args.knowledge_id} not found")
            return 1
        name = kb.collection_name or kb.index_name
        print(f"knowledge {kb.id} ({kb.name}) -> collection {name!r}")
        if not name:
            return 1
        names = [name]
    else:  # --all
        names = sorted(utility.list_collections(using=alias))
        print(f"found {len(names)} collections")

    risky_collections = []
    for name in names:
        risky = _print_collection(alias, name, only_risky=args.only_risky)
        if risky:
            risky_collections.append((name, risky))

    if args.all and risky_collections:
        print(f"\n=== {len(risky_collections)} collection(s) with risky fields ===")
        for name, risky in risky_collections:
            print(f"   {name}: {', '.join(risky)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
