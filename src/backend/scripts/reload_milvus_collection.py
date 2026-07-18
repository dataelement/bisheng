"""Release and reload Milvus collections to recover a stuck query delegator.

Background
----------
Search/query/delete-by-expression fail with::

    <MilvusException: (code=65535, message=failed to search/query delegator NNNN
     for channel ...-dml_X_...: Timestamp lag too large)>

while brand-new inserts into the same collection still succeed. That asymmetry
means the *query delegator* for one DML channel (shard) has fallen behind its
checkpoint — the read path is broken, the write path is not. Knowledge-file
*retry* fails because its first step is a delete-by-expression
(``document_id in [...]``), which routes through that lagging delegator; a fresh
upload is insert-only and is unaffected.

Releasing and re-loading the collection forces the query nodes to re-subscribe
the DML channels and rebuild their delegators, replaying up to the latest
checkpoint. This is the lightest cluster-side recovery and usually clears the
"Timestamp lag too large" condition.

WARNING
-------
While a collection is released it cannot serve search/query. Re-loading takes
seconds to minutes depending on data size. Run during a maintenance window or
when a brief search outage for that knowledge base is acceptable.

Usage (run from src/backend)
----------------------------
    # one collection by name
    python scripts/reload_milvus_collection.py --collection col_xxxx

    # resolve the collection from a knowledge base id
    python scripts/reload_milvus_collection.py --knowledge-id 123

    # several at once
    python scripts/reload_milvus_collection.py --collection col_a --collection col_b

    # inspect load state only, change nothing
    python scripts/reload_milvus_collection.py --collection col_xxxx --dry-run
"""

import argparse
import sys
from typing import List

from pymilvus import Collection, connections, utility

from bisheng.common.services.config_service import settings


def _connect() -> str:
    """Connect to Milvus with the backend connection args. Returns the alias."""
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

    alias = "reload_milvus"
    safe = {k: v for k, v in connection_args.items() if k not in ("password", "token")}
    print(f"Connecting to Milvus: {safe}")
    connections.connect(alias=alias, **connection_args)
    return alias


def _load_state(alias: str, name: str) -> str:
    try:
        return str(utility.load_state(name, using=alias))
    except Exception as e:  # noqa: BLE001
        return f"<unknown: {e}>"


def _reload_one(alias: str, name: str, dry_run: bool) -> bool:
    if not utility.has_collection(name, using=alias):
        print(f"\n## {name}\n   !! collection does not exist, skip")
        return False

    print(f"\n## {name}")
    print(f"   load_state before: {_load_state(alias, name)}")

    if dry_run:
        print("   dry-run: not releasing/loading")
        return True

    col = Collection(name=name, using=alias)
    try:
        print("   releasing ...")
        col.release()
        print("   loading ...")
        col.load()
        utility.wait_for_loading_complete(name, using=alias)
        print(f"   load_state after:  {_load_state(alias, name)}")
        print("   OK — delegator rebuilt")
        return True
    except Exception as e:  # noqa: BLE001
        # Re-loading failed; surface it loudly. The collection may be left
        # released — operators must re-run or load it manually.
        print(f"   !! reload FAILED: {e}")
        print("   collection may be left RELEASED; re-run or load it manually.")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release and reload Milvus collections to recover a stuck query delegator."
    )
    parser.add_argument("--collection", action="append", default=[], help="collection name (repeatable)")
    parser.add_argument("--knowledge-id", type=int, action="append", default=[],
                        help="resolve collection from a knowledge base id (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="only print load state, change nothing")
    args = parser.parse_args()

    if not args.collection and not args.knowledge_id:
        parser.error("provide at least one --collection or --knowledge-id")

    alias = _connect()

    names: List[str] = list(args.collection)
    if args.knowledge_id:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        for kid in args.knowledge_id:
            kb = KnowledgeDao.query_by_id(kid)
            if not kb:
                print(f"knowledge id {kid} not found, skip")
                continue
            name = kb.collection_name or kb.index_name
            print(f"knowledge {kb.id} ({kb.name}) -> collection {name!r}")
            if name:
                names.append(name)

    # de-dup, preserve order
    seen = set()
    names = [n for n in names if not (n in seen or seen.add(n))]

    failed = []
    for name in names:
        if not _reload_one(alias, name, args.dry_run):
            failed.append(name)

    print(f"\n=== done: {len(names) - len(failed)}/{len(names)} reloaded ===")
    if failed:
        print(f"failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
