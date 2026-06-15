from contextlib import contextmanager


class _FakeMappings:
    def __init__(self, rows):
        self.rows = rows
        self.partition_batch_sizes = []

    def __iter__(self):
        return iter(self.rows)

    def partitions(self, batch_size):
        self.partition_batch_sizes.append(batch_size)
        yield self.rows


class _FakeResult:
    def __init__(self, rows):
        self._mappings = _FakeMappings(rows)

    def mappings(self):
        return self._mappings


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.exec_calls = []
        self.last_result = None

    def exec(self, statement, *, params=None):
        self.exec_calls.append({"statement": statement, "params": params})
        self.last_result = _FakeResult(self.rows)
        return self.last_result


def test_fetch_all_passes_sql_params_by_keyword(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_file_increment as module

    session = _FakeSession([{"USER_ID": 1, "USER_NAME": "Alice"}])

    @contextmanager
    def fake_session_factory():
        yield session

    monkeypatch.setattr(module, "get_sync_db_session", fake_session_factory)

    rows = module.fetch_all("SELECT * FROM user WHERE user_id = :user_id", {"user_id": 1})

    assert rows == [{"user_id": 1, "user_name": "Alice"}]
    assert session.exec_calls[0]["params"] == {"user_id": 1}


def test_stream_query_passes_sql_params_by_keyword(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_file_increment as module

    session = _FakeSession([{"FILE_ID": 11}])

    @contextmanager
    def fake_session_factory():
        yield session

    monkeypatch.setattr(module, "get_sync_db_session", fake_session_factory)

    rows = list(module.stream_query("SELECT * FROM knowledgefile WHERE create_time >= :start_time", {"start_time": 1}))

    assert rows == [{"file_id": 11}]
    assert session.exec_calls[0]["params"] == {"start_time": 1}
    assert session.last_result.mappings().partition_batch_sizes == [1000]
