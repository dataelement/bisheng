"""AC-12..27/41/42: real connections and isolated business data, opt-in only.

These tests do not rotate customer accounts. Invoke on a disposable stack after
fresh initialization and after each explicit service-side rotation. The same
read tests must pass after restoring the matching server/client pair.
"""

import io
import uuid

import pytest

from bisheng.core.config.credential_checks import check_online


@pytest.mark.parametrize("component", ["mysql", "redis", "minio", "elasticsearch", "milvus"])
def test_new_authenticated_connection(live_settings, component):
    check_online(live_settings, component)


def test_minio_new_object_roundtrip(live_settings):
    from minio import Minio

    conf = live_settings.object_storage.minio
    client = Minio(
        conf.endpoint,
        access_key=conf.access_key,
        secret_key=conf.secret_key,
        secure=conf.secure,
        cert_check=conf.cert_check,
    )
    bucket = "e2e-credential-" + uuid.uuid4().hex[:20]
    created = False
    try:
        client.make_bucket(bucket)
        created = True
        client.put_object(bucket, "probe", io.BytesIO(b"credential-acceptance"), 21)
        result = client.get_object(bucket, "probe")
        try:
            assert result.read() == b"credential-acceptance"
        finally:
            result.close()
            result.release_conn()
    finally:
        if created:
            client.remove_object(bucket, "probe")
            client.remove_bucket(bucket)
        client._http.clear()


def test_es_new_index_roundtrip(live_settings):
    from elasticsearch import Elasticsearch

    conf = live_settings.vector_stores.elasticsearch
    client = Elasticsearch(conf.elasticsearch_url, **conf.ssl_verify)
    index = "e2e-credential-" + uuid.uuid4().hex
    created = False
    try:
        client.indices.create(index=index)
        created = True
        client.index(index=index, id="probe", document={"value": "acceptance"}, refresh="wait_for")
        assert client.get(index=index, id="probe")["_source"]["value"] == "acceptance"
    finally:
        if created:
            client.indices.delete(index=index)
        client.close()


def test_milvus_new_collection_roundtrip_and_wrong_password_denied(live_settings):
    import grpc
    from pymilvus import MilvusClient
    from pymilvus.exceptions import MilvusException

    args = dict(live_settings.vector_stores.milvus.connection_args)
    host = args.pop("host")
    port = args.pop("port")
    args["uri"] = f"{'https' if args.get('secure') else 'http'}://{host}:{port}"
    collection = "e2e_credential_" + uuid.uuid4().hex
    client = MilvusClient(**args)
    created = False
    try:
        client.create_collection(collection, dimension=2)
        created = True
        client.insert(collection, [{"id": 1, "vector": [0.1, 0.2]}])
        client.flush(collection)
        assert client.query(collection, filter="id == 1")[0]["id"] == 1
    finally:
        if created:
            client.drop_collection(collection)
        client.close()
    wrong = dict(args)
    wrong["timeout"] = 5
    if wrong.get("token"):
        wrong["token"] = wrong["token"].partition(":")[0] + ":" + uuid.uuid4().hex
    else:
        wrong["password"] = uuid.uuid4().hex
    rejected = None
    try:
        with pytest.raises((MilvusException, grpc.RpcError)) as caught:
            rejected = MilvusClient(**wrong)
            rejected.list_collections(timeout=5)
        if isinstance(caught.value, grpc.RpcError):
            assert caught.value.code() == grpc.StatusCode.UNAUTHENTICATED
        else:
            assert any(
                word in str(caught.value).lower() for word in ("authentication", "auth check", "unauthenticated")
            )
    finally:
        if rejected:
            rejected.close()
