"""Execute production boundary methods with isolated external dependencies.

Run with unittest (no application startup / database / network required).
The AST loader compiles the actual methods, not a second implementation.
Full application integration tests remain a separate deployment gate.
"""

import ast
import copy
import json
import os
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(os.environ.get("BISHENG_SECURITY_TEST_ROOT", Path(__file__).resolve().parents[2] / "bisheng"))


class Denied(Exception):
    pass


class Missing(Exception):
    pass


def load_methods(relative, names, namespace, class_name=None):
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    if class_name:
        source = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
        methods = [
            copy.deepcopy(n)
            for n in source.body
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name in names
        ]
        node = ast.ClassDef(name=class_name, bases=[], keywords=[], body=methods, decorator_list=[])
    else:
        methods = [
            copy.deepcopy(n)
            for n in tree.body
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name in names
        ]
        for method in methods:
            method.decorator_list = []
        node = None
    body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    body += [node] if node else methods
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    exec(compile(module, str(ROOT / relative), "exec"), namespace)
    return namespace[class_name] if class_name else namespace


@contextmanager
def stub_modules(mapping):
    modules = {}
    for name, values in mapping.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        modules[name] = module
    with patch.dict(sys.modules, modules):
        yield


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    def make(self, value):
        config = NS(aget_from_db=AsyncMock(return_value=value), get_from_db=Mock(return_value=True))
        captcha = AsyncMock(return_value=False)
        db = Mock()
        ns = {
            "settings": config,
            "UnAuthorizedError": Denied,
            "CaptchaError": Missing,
            "verify_captcha": captcha,
            "User": db,
        }
        service = load_methods("user/domain/services/user.py", {"user_register"}, ns, "UserService")
        return service, config, captcha, db

    async def test_closed_before_captcha_or_database(self):
        for value in [False, "false", "FALSE", "0", 0, "off", None, "invalid"]:
            with self.subTest(value=value):
                service, config, captcha, db = self.make({"enable_registration": value})
                with self.assertRaises(Denied):
                    await service.user_register(NS(captcha_key="k", captcha="c"))
                config.get_from_db.assert_not_called()
                captcha.assert_not_awaited()
                db.assert_not_called()

    async def test_enabled_keeps_existing_captcha_gate(self):
        for value in [True, "true", "1", "yes", 1]:
            service, _, captcha, _ = self.make({"enable_registration": value})
            with self.assertRaises(Missing):
                await service.user_register(NS(captcha_key="k", captcha="c"))
            captcha.assert_awaited_once()

    async def test_missing_key_retains_existing_bootstrap_default(self):
        service, _, captcha, _ = self.make({})
        with self.assertRaises(Missing):
            await service.user_register(NS(captcha_key="k", captcha="c"))
        captcha.assert_awaited_once()


class DatasetTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        self.es = NS(
            search=AsyncMock(
                return_value={
                    "aggregations": {"enum_values": {"buckets": [{"key": "allowed"}]}, "total_count": {"value": 1}}
                }
            )
        )
        self.connect = AsyncMock(return_value=self.es)
        self.actor = NS(super_admin=False, data_scope="all_visible")
        ns = {
            "UnAuthorizedError": Denied,
            "get_es_connection": self.connect,
            "resolve_permission_actor": AsyncMock(side_effect=lambda user: self.actor),
        }
        service = load_methods(
            "telemetry_search/domain/services/dashboard.py", {"get_dataset_field_enums"}, ns, "DashboardService"
        )
        service.get_dataset_options = AsyncMock(
            return_value=[
                NS(es_index_name="known", schema_config={"dimensions": [{"field": "user_name"}], "metrics": []})
            ]
        )
        self.service = service
        self.user = NS(tenant_id=7)
        return service

    async def call(self, index="known", field="user_name", **kwargs):
        with stub_modules(
            {
                "bisheng.core.context.tenant": {
                    "get_admin_scope_tenant_id": lambda: None,
                    "get_current_tenant_id": lambda: 7,
                },
                "bisheng.permission.domain.services.data_scope": {"DATA_SCOPE_ALL": "all_visible"},
            }
        ):
            return await self.service.get_dataset_field_enums(index, field, login_user=self.user, **kwargs)

    async def test_unregistered_and_wildcard_indices_rejected_before_es(self):
        self.make()
        for index in ["*", "known,secret", "known*", "other", "known/secret", "known?", "known:secret"]:
            with self.assertRaises(Denied):
                await self.call(index=index)
        self.connect.assert_not_awaited()

    async def test_unconfigured_fields_rejected(self):
        self.make()
        for field in ["password", "*", "user_name.keyword"]:
            with self.assertRaises(Denied):
                await self.call(field=field)
        self.es.search.assert_not_awaited()

    async def test_invalid_pagination_rejected(self):
        self.make()
        for values in [{"size": 0}, {"size": 101}, {"page": 0}, {"page": 101, "size": 100}]:
            with self.assertRaises(Denied):
                await self.call(**values)
        self.connect.assert_not_awaited()

    async def test_valid_tenant_query_is_scoped_and_bounded(self):
        self.make()
        result = await self.call()
        self.assertEqual(result["enums"], ["allowed"])
        args = self.es.search.await_args.kwargs
        self.assertEqual(args["index"], "known")
        self.assertEqual(args["body"]["query"], {"term": {"tenant_id": 7}})
        self.assertEqual(args["body"]["aggs"]["enum_values"]["terms"]["size"], 20)

    async def test_global_admin_can_query_global_dataset(self):
        self.make()
        self.actor.super_admin = True
        await self.call()
        self.assertNotIn("query", self.es.search.await_args.kwargs["body"])

    async def test_narrowed_actor_cannot_export_enums(self):
        self.make()
        self.actor.data_scope = "personal_only"
        with self.assertRaises(Denied):
            await self.call()
        self.connect.assert_not_awaited()

    async def test_catalog_requires_dashboard_access(self):
        ns = {
            "UnAuthorizedError": Denied,
            "WebMenuResource": NS(BOARD=NS(value="board")),
            "AccessType": NS(WEB_MENU=99),
            "get_async_db_session": Mock(),
        }
        service = load_methods(
            "telemetry_search/domain/services/dashboard.py", {"get_dataset_options"}, ns, "DashboardService"
        )
        user = NS(async_access_check=AsyncMock(return_value=False))
        with self.assertRaises(Denied):
            await service.get_dataset_options(user)
        ns["get_async_db_session"].assert_not_called()


class FileSigningTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_uses_unique_server_keys_and_stamps_owner(self):
        from datetime import datetime
        from urllib.parse import unquote
        from uuid import uuid4

        storage = NS(minio_config=NS(endpoint="minio"), clear_minio_share_host=lambda value: value)
        save = AsyncMock(return_value="/tmp-dir/workstation-uploads/test.mp4")
        timer = NS(stage=Mock(), finish=Mock(), fail=Mock())
        ns = {
            "get_minio_storage": AsyncMock(return_value=storage),
            "save_uploaded_file": save,
            "_resolve_leaf_tenant_id": lambda user: user.tenant_id,
            "WorkstationMediaCoverService": NS(is_video_filename=lambda name: True),
            "MediaUploadStageTimer": lambda *a, **k: timer,
            "resp_200": lambda **kw: kw,
            "File": lambda *a, **k: None,
            "Form": lambda *a, **k: None,
            "LoginUserDep": None,
            "uuid4": uuid4,
            "datetime": datetime,
            "unquote": unquote,
            "ServerError": RuntimeError,
        }
        function = load_methods("workstation/api/endpoints/knowledge.py", {"upload_file"}, ns)["upload_file"]
        file = NS(filename="original.mp4", content_type="video/mp4", close=AsyncMock())
        for _ in range(2):
            result = await function(None, file, "f1", NS(user_id=7, tenant_id=2))
            self.assertEqual(result["data"]["filename"], "original.mp4")
        calls = save.await_args_list
        self.assertNotEqual(calls[0].args[2], calls[1].args[2])
        self.assertTrue(calls[0].args[2].startswith("workstation-uploads/"))
        self.assertEqual(calls[0].kwargs["metadata"], {"owner-user-id": "7", "owner-tenant-id": "2"})

    def make(self, metadata=None):
        self.storage = NS(
            bucket="bisheng",
            tmp_bucket="tmp-dir",
            get_object_metadata=AsyncMock(return_value=metadata or {}),
            get_share_link=AsyncMock(return_value="signed"),
            object_exists=AsyncMock(return_value=True),
        )
        from urllib.parse import unquote, urlparse

        ns = {
            "UnAuthorizedError": Denied,
            "ServerError": Denied,
            "get_minio_storage": AsyncMock(return_value=self.storage),
            "_resolve_leaf_tenant_id": lambda user: user.tenant_id,
            "resp_200": lambda **kw: kw,
            "Query": lambda *a, **k: None,
            "LoginUserDep": None,
            "unquote": unquote,
            "urlparse": urlparse,
        }
        self.functions = load_methods(
            "workstation/api/endpoints/knowledge.py", {"_resolve_minio_object_from_filepath", "get_file_share_url"}, ns
        )
        return self.functions

    async def test_knowledge_and_other_paths_cannot_be_signed(self):
        self.make()
        for path in ["/bisheng/original/13.txt", "/tmp-dir/old.mp4", "/other/workstation-uploads/x.mp4"]:
            with self.assertRaises(Denied):
                await self.functions["get_file_share_url"](path, NS(user_id=7, tenant_id=2))
        self.storage.get_share_link.assert_not_awaited()

    async def test_owner_renews_uploaded_file(self):
        self.make({"x-amz-meta-owner-user-id": "7", "x-amz-meta-owner-tenant-id": "2"})
        result = await self.functions["get_file_share_url"](
            "/tmp-dir/workstation-uploads/x.mp4?old=sig", NS(user_id=7, tenant_id=2)
        )
        self.assertEqual(result, {"data": {"url": "signed"}})
        self.storage.get_share_link.assert_awaited_once_with(
            "workstation-uploads/x.mp4", bucket="tmp-dir", expire_days=1
        )

    async def test_other_user_or_tenant_cannot_renew(self):
        self.make({"x-amz-meta-owner-user-id": "7", "x-amz-meta-owner-tenant-id": "2"})
        for user in [NS(user_id=8, tenant_id=2), NS(user_id=7, tenant_id=3)]:
            with self.assertRaises(Denied):
                await self.functions["get_file_share_url"]("/tmp-dir/workstation-uploads/x.mp4", user)
        self.storage.get_share_link.assert_not_awaited()

    async def test_unstamped_legacy_upload_fails_closed(self):
        self.make()
        with self.assertRaises(Denied):
            await self.functions["get_file_share_url"]("/tmp-dir/workstation-uploads/x.mp4", NS(user_id=7, tenant_id=2))
        self.storage.get_share_link.assert_not_awaited()

    async def test_encoded_path_does_not_bypass_ownership(self):
        self.make()
        for path in [
            "/tmp-dir/workstation-uploads/%252e%252e/original/13.txt",
            "https://host/tmp-dir/workstation-uploads/x.mp4",
        ]:
            with self.assertRaises(Denied):
                await self.functions["get_file_share_url"](path, NS(user_id=7, tenant_id=2))
        self.storage.get_share_link.assert_not_awaited()


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        self.session = NS(
            chat_id="c1", user_id=7, tenant_id=2, is_delete=False, api_subject_type=None, flow_id="flow1", group_ids=[]
        )
        self.user = NS(user_id=7, tenant_id=2, is_global_super=False, is_admin=lambda: False)

        def subject(**kw):
            return NS(
                matches=lambda row: row.user_id == kw["user_id"]
                and row.tenant_id == kw["tenant_id"]
                and row.api_subject_type is None
            )

        self.audit = NS(
            _get_audit_tenant_scope=lambda user: user.tenant_id, _user_has_log_web_menu=AsyncMock(return_value=False)
        )
        self.tasks = NS(get_task_byid=Mock(return_value=None), get_user_tasks=Mock(return_value=[]))
        self.dao = NS(async_get_one=AsyncMock(side_effect=lambda _: self.session))
        self.groups = NS(aget_user_admin_group=AsyncMock(return_value=[]))
        ns = {
            "UnAuthorizedError": Denied,
            "NotFoundError": Missing,
            "SessionSubject": NS(natural_person=subject),
            "_resolve_leaf_tenant_id": lambda user: user.tenant_id,
            "AuditLogService": self.audit,
            "MessageSessionDao": self.dao,
            "MarkTaskDao": self.tasks,
            "UserGroupDao": self.groups,
            "json": json,
        }
        self.service = load_methods(
            "chat_session/domain/chat.py", {"can_read_session", "require_session_read"}, ns, "ChatSessionService"
        )

    async def test_owner_allowed(self):
        self.make()
        self.assertIs(await self.service.require_session_read("c1", self.user), self.session)

    async def test_same_tenant_stranger_denied(self):
        self.make()
        self.user.user_id = 8
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user)

    async def test_cross_tenant_admin_denied(self):
        self.make()
        self.user.tenant_id = 3
        self.user.is_admin = lambda: True
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user)

    async def test_admin_within_scope_allowed(self):
        self.make()
        self.user.user_id = 8
        self.user.is_admin = lambda: True
        await self.service.require_session_read("c1", self.user)

    async def test_log_menu_within_scope_allowed(self):
        self.make()
        self.user.user_id = 8
        self.audit._user_has_log_web_menu.return_value = True
        await self.service.require_session_read("c1", self.user)

    async def test_service_account_not_mistaken_for_person_owner(self):
        self.make()
        self.session.api_subject_type = "service_account"
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user)

    async def test_group_admin_only_matches_recorded_groups(self):
        self.make()
        self.user.user_id = 8
        self.groups.aget_user_admin_group.return_value = [NS(group_id=10)]
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user)
        self.session.group_ids = '["10"]'
        await self.service.require_session_read("c1", self.user)

    async def test_annotation_requires_exact_user_app_and_tenant(self):
        self.make()
        self.user.user_id = 8
        self.tasks.get_task_byid.return_value = NS(tenant_id=2, process_users="18", app_id="flow1")
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user, 1)
        self.tasks.get_task_byid.return_value.process_users = "8"
        await self.service.require_session_read("c1", self.user, 1)
        self.tasks.get_task_byid.return_value.app_id = "other"
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user, 1)

    async def test_deleted_and_missing_refused(self):
        self.make()
        self.session.is_delete = True
        with self.assertRaises(Missing):
            await self.service.require_session_read("c1", self.user)
        self.session = None
        with self.assertRaises(Missing):
            await self.service.require_session_read("c1", self.user)

    async def test_missing_tenant_context_does_not_expand_admin_scope(self):
        self.make()
        self.audit._get_audit_tenant_scope = lambda user: None
        self.user.tenant_id = 3
        self.user.is_admin = lambda: True
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user)

    async def test_annotation_history_without_task_parameter_uses_persisted_assignment(self):
        self.make()
        self.user.user_id = 8
        task = NS(tenant_id=2, process_users="8", app_id="flow1")
        self.tasks.get_user_tasks.return_value = [task]
        await self.service.require_session_read("c1", self.user)
        task.app_id = "other"
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user)
        task.app_id = "flow1"
        task.tenant_id = 3
        with self.assertRaises(Denied):
            await self.service.require_session_read("c1", self.user)


class SessionListTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        rows = [
            NS(
                chat_id="c1",
                user_id=7,
                tenant_id=2,
                flow_id="allowed",
                flow_name="A",
                flow_type=10,
                create_time=None,
                like=0,
                dislike=0,
                copied=0,
                is_delete=False,
            ),
            NS(
                chat_id="c2",
                user_id=8,
                tenant_id=2,
                flow_id="other",
                flow_name="B",
                flow_type=10,
                create_time=None,
                like=0,
                dislike=0,
                copied=0,
                is_delete=False,
            ),
        ]
        self.filter = Mock(
            side_effect=lambda flow_ids, user_ids: [
                r for r in rows if (not flow_ids or r.flow_id in flow_ids) and (not user_ids or r.user_id in user_ids)
            ]
        )
        self.task = NS(tenant_id=2, process_users="7", app_id="allowed")
        ns = {
            "PageList": lambda **kwargs: NS(**kwargs),
            "AppChatList": lambda **kwargs: NS(**kwargs),
            "UnAuthorizedError": Denied,
            "_resolve_leaf_tenant_id": lambda user: user.tenant_id,
            "MarkTaskDao": NS(get_task_byid=Mock(side_effect=lambda _: self.task)),
            "MessageSessionDao": NS(filter_session=self.filter),
            "MarkRecordDao": NS(filter_records=Mock(return_value=[])),
            "MarkRecordStatus": NS(DEFAULT=NS(value=0)),
            "FlowDao": NS(get_flow_list_by_name=Mock(return_value=[NS(id="other")])),
            "AssistantDao": NS(get_all_assistants=Mock(return_value=([], 0))),
            "UserDao": NS(search_user_by_name=Mock(return_value=[])),
        }
        service = load_methods("chat_session/domain/chat.py", {"get_app_chat_list"}, ns, "ChatSessionService")
        service.can_read_session = AsyncMock(side_effect=lambda session, user: session.user_id == user.user_id)
        self.service = service
        self.user = NS(user_id=7, tenant_id=2, is_admin=lambda: False)

    async def test_default_list_does_not_return_other_users(self):
        self.make()
        result = await self.service.get_app_chat_list(login_user=self.user)
        self.assertEqual([item.chat_id for item in result.list], ["c1"])
        self.assertEqual(result.total, 1)

    async def test_annotation_keyword_cannot_escape_task_apps(self):
        self.make()
        result = await self.service.get_app_chat_list(login_user=self.user, task_id=1, keyword="other")
        self.assertEqual(result.list, [])
        self.filter.assert_not_called()

    async def test_empty_annotation_scope_returns_no_sessions(self):
        self.make()
        self.task.app_id = ""
        result = await self.service.get_app_chat_list(login_user=self.user, task_id=1)
        self.assertEqual(result.list, [])
        self.filter.assert_not_called()

    async def test_valid_annotation_scope_preserved(self):
        self.make()
        result = await self.service.get_app_chat_list(login_user=self.user, task_id=1)
        self.assertEqual([item.chat_id for item in result.list], ["c1"])


if __name__ == "__main__":
    unittest.main()
