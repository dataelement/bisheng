#!/usr/bin/env python3
"""在 backend 容器内读写 Milvus / ES. 禁止覆盖已存在的目标, 禁止碰 A 空间名.

用法 (容器内):
  python vector_runtime.py describe --out /tmp/desc.json
  python vector_runtime.py export-milvus --collection col --expr 'file_id>=0' --out /tmp/a.jsonl
  python vector_runtime.py import-milvus --collection dest --schema s.json --src /tmp/a.jsonl --forbid-file names.txt
  python vector_runtime.py export-es --index idx --out /tmp/e.jsonl
  python vector_runtime.py import-es --index dest --mapping m.json --src /tmp/e.jsonl --forbid-file names.txt
  python vector_runtime.py drop-milvus --collection dest --forbid-file names.txt
  python vector_runtime.py drop-es --index dest --forbid-file names.txt
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return jsonable(value.tolist())
    return str(value)


def load_forbid(path: str) -> set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.exists():
        return set()
    return {
        ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()
    }


def assert_allowed(name: str, forbid: set[str]) -> None:
    if not name:
        raise SystemExit("empty store name")
    if name in forbid:
        raise SystemExit(f"refuse A-space or forbidden store {name}")


def milvus_connect():
    from pymilvus import connections

    raw = os.environ.get("BS_MILVUS_CONNECTION_ARGS") or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        args = {}
    host = str(args.pop("host", "127.0.0.1") or "127.0.0.1")
    port = str(args.pop("port", "19530") or "19530")
    uri = args.get("uri") or f"http://{host}:{port}"
    kwargs = {
        k: args[k]
        for k in ("user", "password", "token", "db_name")
        if args.get(k) not in (None, "")
    }
    connections.connect(alias="fusion", uri=uri, **kwargs)
    return "fusion"


def es_kwargs_from_env(raw: str | None) -> dict:
    """解析 BS_ELASTICSEARCH_SSL_VERIFY. JSON 里 basic_auth 是 list, 客户端要 tuple."""
    import ast

    text = (raw or "").strip() or "{}"
    try:
        kwargs = json.loads(text)
    except json.JSONDecodeError:
        try:
            kwargs = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            kwargs = {}
    if not isinstance(kwargs, dict):
        return {}
    auth = kwargs.get("basic_auth")
    if isinstance(auth, list):
        kwargs = dict(kwargs)
        kwargs["basic_auth"] = tuple(auth)
    return kwargs


def es_client():
    from elasticsearch import Elasticsearch

    url = os.environ.get("BS_ELASTICSEARCH_URL") or "http://127.0.0.1:9200"
    return Elasticsearch(
        hosts=url, **es_kwargs_from_env(os.environ.get("BS_ELASTICSEARCH_SSL_VERIFY"))
    )


def dtype_name(field) -> str:
    dt = getattr(field, "dtype", None)
    name = getattr(dt, "name", None) or str(dt)
    return str(name).split(".")[-1]


def describe_collection(name: str, alias: str) -> dict:
    from pymilvus import Collection, utility

    if not utility.has_collection(name, using=alias):
        return {}
    col = Collection(name, using=alias)
    try:
        col.load()
    except Exception:
        pass
    fields = []
    for f in col.schema.fields:
        item = {
            "name": f.name,
            "dtype": dtype_name(f),
            "is_primary": bool(f.is_primary),
            "auto_id": bool(getattr(f, "auto_id", False)),
            "params": dict(getattr(f, "params", None) or {}),
        }
        if getattr(f, "max_length", None):
            item["params"]["max_length"] = f.max_length
        fields.append(item)
    indexes = []
    try:
        for idx in col.indexes:
            params = dict(getattr(idx, "params", None) or {})
            indexes.append(
                {
                    "field": getattr(idx, "field_name", "") or params.get("field_name"),
                    "index_type": params.get("index_type") or params.get("indexType"),
                    "metric_type": params.get("metric_type")
                    or params.get("metricType"),
                    "params": params,
                }
            )
    except Exception:
        indexes = []
    partitions = []
    try:
        partitions = [p.name for p in col.partitions]
    except Exception:
        partitions = []
    return {
        "fields": fields,
        "indexes": indexes,
        "partitions": partitions,
        "num_entities": int(col.num_entities or 0),
    }


def describe_index(es, name: str) -> dict:
    if not es.indices.exists(index=name):
        return {}
    mapping = es.indices.get_mapping(index=name)
    body = mapping.get(name) or next(iter(mapping.values()), {})
    count = es.count(index=name)
    settings = es.indices.get_settings(index=name)
    set_body = settings.get(name) or next(iter(settings.values()), {})
    analysis = ((set_body.get("settings") or {}).get("index") or {}).get(
        "analysis"
    ) or {}
    return {
        "mappings": body.get("mappings") or {},
        "docs": int((count or {}).get("count") or 0),
        "analysis": analysis,
    }


def cmd_describe(args: argparse.Namespace) -> int:
    out = {"collections": {}, "indices": {}}
    alias = milvus_connect()
    from pymilvus import utility

    for name in utility.list_collections(using=alias):
        out["collections"][name] = describe_collection(name, alias)
    try:
        es = es_client()
        try:
            names = list(es.indices.get(index="*,-.*").keys())
        except Exception:
            names = [i["index"] for i in (es.cat.indices(format="json") or [])]
        for name in names:
            if str(name).startswith("."):
                continue
            out["indices"][name] = describe_index(es, name)
    except Exception as exc:
        out["es_error"] = str(exc)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(args.out)
    return 0


def cmd_export_milvus(args: argparse.Namespace) -> int:
    alias = milvus_connect()
    from pymilvus import Collection, utility

    if not utility.has_collection(args.collection, using=alias):
        raise SystemExit(f"missing collection {args.collection}")
    col = Collection(args.collection, using=alias)
    col.load()
    fields = [f.name for f in col.schema.fields if not f.is_primary]
    expr = args.expr or ""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as f:
        iterator = col.query_iterator(
            batch_size=int(args.batch_size),
            expr=expr or None,
            output_fields=fields,
            timeout=120,
        )
        try:
            while True:
                page = iterator.next()
                if not page:
                    break
                for row in page:
                    f.write(json.dumps(jsonable(row), ensure_ascii=False) + "\n")
                    n += 1
        finally:
            try:
                iterator.close()
            except Exception:
                pass
    print(f"exported={n} -> {out}")
    return 0


def _data_type(name: str):
    from pymilvus import DataType

    key = str(name or "").split(".")[-1].upper()
    if not hasattr(DataType, key):
        raise SystemExit(f"unsupported milvus dtype {name}")
    return getattr(DataType, key)


def schema_from_json(payload: dict):
    from pymilvus import CollectionSchema, DataType, FieldSchema

    fields = []
    has_pk = False
    for item in payload.get("fields") or []:
        name = item.get("name")
        if not name:
            continue
        if item.get("is_primary"):
            fields.append(
                FieldSchema(
                    name=name,
                    dtype=DataType.INT64,
                    is_primary=True,
                    auto_id=True,
                )
            )
            has_pk = True
            continue
        dtype = _data_type(item.get("dtype"))
        params = dict(item.get("params") or {})
        kwargs = {}
        if "max_length" in params:
            kwargs["max_length"] = int(params["max_length"])
        if "dim" in params:
            kwargs["dim"] = int(params["dim"])
        if "max_capacity" in params:
            kwargs["max_capacity"] = int(params["max_capacity"])
        if "element_type" in params:
            kwargs["element_type"] = _data_type(params["element_type"])
        fields.append(FieldSchema(name=name, dtype=dtype, **kwargs))
    if not has_pk:
        fields.insert(
            0,
            FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
        )
    return CollectionSchema(fields=fields)


def default_index_params(schema_payload: dict) -> dict:
    for idx in schema_payload.get("indexes") or []:
        metric = idx.get("metric_type") or "L2"
        itype = str(idx.get("index_type") or "HNSW").upper()
        if itype not in {"HNSW", "FLAT", "IVF_FLAT", "IVF_SQ8", "AUTOINDEX"}:
            itype = "HNSW"
        params = {
            "index_type": itype,
            "metric_type": metric,
            "params": {"M": 8, "efConstruction": 64},
        }
        if itype.startswith("IVF"):
            params["params"] = {"nlist": 1024}
        field = idx.get("field") or "vector"
        return {"field": field, **params}
    return {
        "field": "vector",
        "index_type": "HNSW",
        "metric_type": "L2",
        "params": {"M": 8, "efConstruction": 64},
    }


def cmd_import_milvus(args: argparse.Namespace) -> int:
    forbid = load_forbid(args.forbid_file)
    assert_allowed(args.collection, forbid)
    alias = milvus_connect()
    from pymilvus import Collection, utility

    if utility.has_collection(args.collection, using=alias):
        print(f"skipped-exists collection={args.collection}")
        return 0
    schema_payload = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    schema = schema_from_json(schema_payload)
    col = Collection(name=args.collection, schema=schema, using=alias)
    target_fields = [f.name for f in col.schema.fields if not f.is_primary]
    rows = []
    src = Path(args.src)
    if src.exists() and src.stat().st_size:
        with src.open(encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    rows.append(json.loads(ln))
    if rows:
        insert_list = [[row.get(field) for row in rows] for field in target_fields]
        col.insert(insert_list, timeout=120)
    idx = default_index_params(schema_payload)
    vec_field = idx.pop("field")
    try:
        col.create_index(vec_field, idx)
    except Exception:
        col.create_index(
            vec_field,
            {
                "index_type": "HNSW",
                "metric_type": "L2",
                "params": {"M": 8, "efConstruction": 64},
            },
        )
    col.load()
    print(f"imported={len(rows)} collection={args.collection}")
    return 0


def cmd_export_es(args: argparse.Namespace) -> int:
    from elasticsearch.helpers import scan

    es = es_client()
    if not es.indices.exists(index=args.index):
        raise SystemExit(f"missing index {args.index}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    query: dict[str, Any] = {"query": {"match_all": {}}}
    if args.query:
        query = json.loads(args.query)
        if "query" not in query:
            query = {"query": query}
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for hit in scan(es, index=args.index, query=query, size=int(args.batch_size)):
            src = hit.get("_source") or {}
            f.write(json.dumps(jsonable(src), ensure_ascii=False) + "\n")
            n += 1
    print(f"exported={n} -> {out}")
    return 0


def sanitize_es_mapping(mapping: dict) -> dict:
    """去掉 A 没有的 similarity 插件名 (如 custom_bm25), 落到默认 BM25. 不改字段名."""
    drop = {"custom_bm25"}

    def walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for key, val in obj.items():
                if key == "similarity" and isinstance(val, str) and val in drop:
                    continue
                out[key] = walk(val)
            return out
        if isinstance(obj, list):
            return [walk(item) for item in obj]
        return obj

    return walk(mapping)


def cmd_import_es(args: argparse.Namespace) -> int:
    from elasticsearch.helpers import bulk

    forbid = load_forbid(args.forbid_file)
    assert_allowed(args.index, forbid)
    es = es_client()
    if es.indices.exists(index=args.index):
        print(f"skipped-exists index={args.index}")
        return 0
    mapping = sanitize_es_mapping(
        json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    )
    body: dict[str, Any] = {}
    if mapping.get("mappings"):
        body["mappings"] = mapping["mappings"]
    elif "properties" in mapping:
        body["mappings"] = {"properties": mapping["properties"]}
    es.indices.create(index=args.index, body=body or None)
    actions = []
    src = Path(args.src)
    if src.exists() and src.stat().st_size:
        with src.open(encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                doc = json.loads(ln)
                actions.append(
                    {"_op_type": "index", "_index": args.index, "_source": doc}
                )
    if actions:
        bulk(es, actions, raise_on_error=True)
        es.indices.refresh(index=args.index)
    print(f"imported={len(actions)} index={args.index}")
    return 0


def cmd_drop_milvus(args: argparse.Namespace) -> int:
    forbid = load_forbid(args.forbid_file)
    assert_allowed(args.collection, forbid)
    alias = milvus_connect()
    from pymilvus import utility

    if utility.has_collection(args.collection, using=alias):
        utility.drop_collection(args.collection, using=alias)
        print(f"dropped collection {args.collection}")
    else:
        print(f"absent collection {args.collection}")
    return 0


def cmd_drop_es(args: argparse.Namespace) -> int:
    forbid = load_forbid(args.forbid_file)
    assert_allowed(args.index, forbid)
    es = es_client()
    if es.indices.exists(index=args.index):
        es.indices.delete(index=args.index)
        print(f"dropped index {args.index}")
    else:
        print(f"absent index {args.index}")
    return 0


def vector_field_name(col) -> str:
    for field in col.schema.fields:
        name = dtype_name(field).upper()
        if "VECTOR" in name:
            return field.name
    return "vector"


def cmd_sample_milvus(args: argparse.Namespace) -> int:
    alias = milvus_connect()
    from pymilvus import Collection, utility

    if not utility.has_collection(args.collection, using=alias):
        raise SystemExit(f"missing collection {args.collection}")
    col = Collection(args.collection, using=alias)
    col.load()
    vec_field = vector_field_name(col)
    fields = [f.name for f in col.schema.fields if not f.is_primary]
    limit = int(args.limit)
    rows: list[dict] = []
    iter_kw = {
        "batch_size": min(64, max(limit, 8)),
        "output_fields": fields,
        "timeout": 120,
    }
    expr = (getattr(args, "expr", None) or "").strip()
    if expr:
        iter_kw["expr"] = expr
    iterator = col.query_iterator(**iter_kw)
    try:
        while len(rows) < limit:
            page = iterator.next()
            if not page:
                break
            for row in page:
                if row.get(vec_field) is None:
                    continue
                rows.append(jsonable(row))
                if len(rows) >= limit:
                    break
    finally:
        try:
            iterator.close()
        except Exception:
            pass
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"sampled={len(rows)} -> {out}")
    return 0


def _hit_value(hit, key: str):
    entity = getattr(hit, "entity", None)
    if entity is not None:
        try:
            return entity.get(key)
        except Exception:
            pass
    return getattr(hit, key, None)


def cmd_search_milvus(args: argparse.Namespace) -> int:
    alias = milvus_connect()
    from pymilvus import Collection, utility

    if not utility.has_collection(args.collection, using=alias):
        raise SystemExit(f"missing collection {args.collection}")
    col = Collection(args.collection, using=alias)
    col.load()
    vec_field = vector_field_name(col)
    if args.vector_file:
        raw = json.loads(Path(args.vector_file).read_text(encoding="utf-8"))
    else:
        raw = json.loads(args.vector)
    if isinstance(raw, dict):
        raw = raw.get("vector") or raw.get(vec_field)
    if not isinstance(raw, list):
        raise SystemExit("vector must be a JSON list")
    output_fields = [
        f.name
        for f in col.schema.fields
        if f.name in {"file_id", "document_id", "knowledge_id"}
    ]
    res = col.search(
        data=[raw],
        anns_field=vec_field,
        param={"metric_type": args.metric, "params": {"ef": 64, "nprobe": 16}},
        limit=int(args.limit),
        output_fields=output_fields or None,
        timeout=120,
    )
    hits = []
    for hit in res[0] if res else []:
        item = {
            "distance": getattr(hit, "distance", None),
            "file_id": _hit_value(hit, "file_id"),
            "document_id": _hit_value(hit, "document_id"),
            "knowledge_id": _hit_value(hit, "knowledge_id"),
        }
        hits.append(item)
    Path(args.out).write_text(json.dumps(hits, ensure_ascii=False), encoding="utf-8")
    print(f"hits={len(hits)} -> {args.out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("describe")
    d.add_argument("--out", required=True)
    d.set_defaults(func=cmd_describe)

    e = sub.add_parser("export-milvus")
    e.add_argument("--collection", required=True)
    e.add_argument("--expr", default="")
    e.add_argument("--out", required=True)
    e.add_argument("--batch-size", default="500")
    e.set_defaults(func=cmd_export_milvus)

    i = sub.add_parser("import-milvus")
    i.add_argument("--collection", required=True)
    i.add_argument("--schema", required=True)
    i.add_argument("--src", required=True)
    i.add_argument("--forbid-file", default="")
    i.set_defaults(func=cmd_import_milvus)

    ee = sub.add_parser("export-es")
    ee.add_argument("--index", required=True)
    ee.add_argument("--query", default="")
    ee.add_argument("--out", required=True)
    ee.add_argument("--batch-size", default="500")
    ee.set_defaults(func=cmd_export_es)

    ie = sub.add_parser("import-es")
    ie.add_argument("--index", required=True)
    ie.add_argument("--mapping", required=True)
    ie.add_argument("--src", required=True)
    ie.add_argument("--forbid-file", default="")
    ie.set_defaults(func=cmd_import_es)

    dm = sub.add_parser("drop-milvus")
    dm.add_argument("--collection", required=True)
    dm.add_argument("--forbid-file", default="")
    dm.set_defaults(func=cmd_drop_milvus)

    de = sub.add_parser("drop-es")
    de.add_argument("--index", required=True)
    de.add_argument("--forbid-file", default="")
    de.set_defaults(func=cmd_drop_es)

    sm = sub.add_parser("sample-milvus")
    sm.add_argument("--collection", required=True)
    sm.add_argument("--out", required=True)
    sm.add_argument("--limit", default="3")
    sm.add_argument("--expr", default="")
    sm.set_defaults(func=cmd_sample_milvus)

    se = sub.add_parser("search-milvus")
    se.add_argument("--collection", required=True)
    se.add_argument("--out", required=True)
    se.add_argument("--vector", default="")
    se.add_argument("--vector-file", default="")
    se.add_argument("--limit", default="5")
    se.add_argument("--metric", default="L2")
    se.set_defaults(func=cmd_search_milvus)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
