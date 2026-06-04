"""Find Milvus collections whose query delegator is broken (timestamp lag etc.).

Background
----------
When a query delegator falls behind its checkpoint, search/query/delete-by-
expression on that collection fail with::

    failed to search/query delegator NNNN for channel ...-dml_X_...:
    Timestamp lag too large

while plain inserts keep working (write path != read path). The symptom *is*
the query failing, so the most reliable client-side detection is to send a
minimal probe query to each collection and see which ones raise.

This script scans collections, fires a tiny strong-consistency probe query
(which forces the delegator to serve at the latest timestamp, the worst case
for a lagging delegator), and reports which collections are unhealthy — mapping
each back to its knowledge base for readability.

Usage (run from src/backend)
----------------------------
    # scan every collection on the server
    python scripts/diagnose_milvus_collections.py --all

    # scan only the collections backing specific knowledge bases
    python scripts/diagnose_milvus_collections.py --knowledge-id 123 --knowledge-id 456

    # scan named collections
    python scripts/diagnose_milvus_collections.py --collection col_a --collection col_b

By default unloaded collections are skipped (a released collection cannot be
probed); pass --load-unloaded to load them first (heavier).
"""

import argparse
import sys
from typing import Dict, List, Optional, Tuple

from pymilvus import Collection, connections, utility

from bisheng.common.services.config_service import settings

# Substrings that identify a delegator/consistency problem specifically.
_DELEGATOR_MARKERS = ("timestamp lag too large", "delegator", "channel checkpoint", "not ready")

PROBE_TIMEOUT = 15.0


def _connect() -> str:
    conf = settings.get_vectors_conf().milvus
    connection_args = dict(conf.connection_args or {})
    if not connection_args:
        raise RuntimeError(
            "No milvus connection_args configured. Check vectorstores.milvus in config.yaml."
        )
    if connection_args.get("host") and connection_args.get("port"):
        host = connection_args.pop("host")
        port = connection_args.pop("port")
        connection_args["uri"] = f"http://{host}:{port}"

    alias = "diagnose_milvus"
    safe = {k: v for k, v in connection_args.items() if k not in ("password", "token")}
    print(f"Connecting to Milvus: {safe}")
    connections.connect(alias=alias, **connection_args)
    return alias


def _collection_to_knowledge() -> Dict[str, str]:
    """Map collection_name -> 'kb_id:kb_name' for readable output."""
    mapping: Dict[str, str] = {}
    try:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        page = 1
        while True:
            rows = KnowledgeDao.get_all_knowledge(page=page, limit=500)
            if not rows:
                break
            for kb in rows:
                name = kb.collection_name or kb.index_name
                if name:
                    mapping.setdefault(name, f"{kb.id}:{kb.name}")
            page += 1
    except Exception as e:  # noqa: BLE001
        print(f"(warning) could not load knowledge mapping: {e}")
    return mapping


def _primary_field(col: Collection) -> Optional[str]:
    for f in col.schema.fields:
        if f.to_dict().get("is_primary"):
            return f.name
    return None


def _probe(alias: str, name: str, load_unloaded: bool) -> Tuple[str, str]:
    """Return (status, detail). status in {OK, LAG, ERROR, SKIPPED}."""
    try:
        state = str(utility.load_state(name, using=alias))
    except Exception as e:  # noqa: BLE001
        return "ERROR", f"load_state failed: {e}"

    if "Loaded" not in state:
        if not load_unloaded:
            return "SKIPPED", f"not loaded ({state}); use --load-unloaded to probe"
        try:
            Collection(name=name, using=alias).load()
            utility.wait_for_loading_complete(name, using=alias)
        except Exception as e:  # noqa: BLE001
            return "ERROR", f"load failed: {e}"

    col = Collection(name=name, using=alias)
    pk = _primary_field(col)
    if not pk:
        return "ERROR", "no primary key field found"

    # Strong consistency forces the delegator to serve at the latest ts — the
    # exact path that trips "Timestamp lag too large" when it is behind.
    try:
        col.query(
            expr=f"{pk} >= 0",
            output_fields=[pk],
            limit=1,
            consistency_level="Strong",
            timeout=PROBE_TIMEOUT,
        )
        return "OK", ""
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        low = msg.lower()
        if any(m in low for m in _DELEGATOR_MARKERS):
            return "LAG", msg
        return "ERROR", msg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Milvus collections and report which have a broken query delegator."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="scan all collections on the server")
    group.add_argument("--collection", action="append", default=[], help="collection name (repeatable)")
    group.add_argument("--knowledge-id", type=int, action="append", default=[],
                       help="knowledge base id (repeatable)")
    parser.add_argument("--load-unloaded", action="store_true",
                        help="load released collections before probing (heavier)")
    args = parser.parse_args()

    alias = _connect()
    kb_map = _collection_to_knowledge()

    if args.all:
        names: List[str] = sorted(utility.list_collections(using=alias))
        print(f"scanning {len(names)} collections")
    elif args.collection:
        names = list(args.collection)
    else:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        names = []
        for kid in args.knowledge_id:
            kb = KnowledgeDao.query_by_id(kid)
            if not kb:
                print(f"knowledge id {kid} not found, skip")
                continue
            n = kb.collection_name or kb.index_name
            if n:
                names.append(n)

    bad_lag: List[Tuple[str, str]] = []
    other_err: List[Tuple[str, str]] = []
    skipped: List[str] = []

    for name in names:
        status, detail = _probe(alias, name, args.load_unloaded)
        kb = kb_map.get(name, "-")
        line = f"[{status:7}] {name}  (kb {kb})"
        if status == "OK":
            print(line)
        elif status == "SKIPPED":
            print(f"{line}  {detail}")
            skipped.append(name)
        elif status == "LAG":
            print(f"{line}\n           -> {detail}")
            bad_lag.append((name, kb))
        else:
            print(f"{line}\n           -> {detail}")
            other_err.append((name, kb))

    print("\n=== summary ===")
    print(f"probed: {len(names)}  ok: {len(names) - len(bad_lag) - len(other_err) - len(skipped)}  "
          f"delegator/lag: {len(bad_lag)}  other_error: {len(other_err)}  skipped: {len(skipped)}")
    if bad_lag:
        print("\nstuck query delegator (timestamp lag) — recover with reload_milvus_collection.py:")
        for name, kb in bad_lag:
            print(f"   {name}  (kb {kb})")
    if other_err:
        print("\nother query errors (investigate):")
        for name, kb in other_err:
            print(f"   {name}  (kb {kb})")

    return 1 if (bad_lag or other_err) else 0


if __name__ == "__main__":
    sys.exit(main())
