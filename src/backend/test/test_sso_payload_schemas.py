"""Tests for F014 payload Pydantic schemas.

The schemas are the contract between Gateway and bisheng — a mistake in
required/optional flags translates directly into 500s in production. Keep
this suite exhaustive about *what is required*, *what defaults to what*,
and *how fallbacks behave*.
"""

import pytest
from pydantic import ValidationError

from bisheng.sso_sync.domain.schemas.payloads import (
    BatchResult,
    DepartmentUpsertItem,
    DepartmentsSyncRequest,
    LoginSyncRequest,
    LoginSyncResponse,
    TenantMappingItem,
    UserAttrsDTO,
)


class TestLoginSyncRequest:

    def test_minimum_required(self):
        req = LoginSyncRequest(external_user_id='u1', ts=1713400000)
        assert req.external_user_id == 'u1'
        assert req.ts == 1713400000
        assert req.primary_dept_external_id is None
        assert req.secondary_dept_external_ids is None
        assert req.tenant_mapping is None
        assert req.root_tenant_id == 1
        assert isinstance(req.user_attrs, UserAttrsDTO)

    def test_external_user_id_required(self):
        with pytest.raises(ValidationError):
            LoginSyncRequest(ts=1)

    def test_ts_required(self):
        with pytest.raises(ValidationError):
            LoginSyncRequest(external_user_id='u1')

    def test_full_payload_round_trip(self):
        raw = {
            'external_user_id': 'u1',
            'primary_dept_external_id': 'D001',
            'secondary_dept_external_ids': ['D002'],
            'user_attrs': {'name': 'Alice', 'email': 'a@x.com'},
            'root_tenant_id': 1,
            'tenant_mapping': [
                {
                    'dept_external_id': 'D001',
                    'tenant_code': 'child1',
                    'tenant_name': 'Child 1',
                }
            ],
            'ts': 1713400000,
        }
        req = LoginSyncRequest.model_validate(raw)
        assert req.user_attrs.name == 'Alice'
        assert req.tenant_mapping[0].tenant_code == 'child1'
        assert req.secondary_dept_external_ids == ['D002']


class TestTenantMappingItem:

    def test_dept_and_tenant_code_required(self):
        with pytest.raises(ValidationError):
            TenantMappingItem(dept_external_id='D1')
        with pytest.raises(ValidationError):
            TenantMappingItem(tenant_code='c', tenant_name='n')

    def test_optional_quota_and_admins(self):
        item = TenantMappingItem(
            dept_external_id='D1',
            tenant_code='c1',
            tenant_name='Name',
        )
        assert item.initial_quota is None
        assert item.initial_admin_external_ids is None


class TestDepartmentsSyncRequest:

    def test_empty_lists_ok(self):
        req = DepartmentsSyncRequest()
        assert req.upsert == []
        assert req.remove == []
        assert req.source_ts is None

    def test_upsert_item_requires_external_id_and_name(self):
        with pytest.raises(ValidationError):
            DepartmentUpsertItem(name='Eng')
        with pytest.raises(ValidationError):
            DepartmentUpsertItem(external_id='D1')

    def test_upsert_top_level_is_valid(self):
        """parent_external_id=None means top-level (Root child)."""
        item = DepartmentUpsertItem(external_id='D1', name='Eng')
        assert item.parent_external_id is None
        assert item.sort == 0
        assert item.ts is None

    def test_parse_full_batch(self):
        raw = {
            'upsert': [
                {'external_id': 'D1', 'name': 'Eng', 'ts': 10},
                {'external_id': 'D2', 'name': 'Mkt', 'parent_external_id': 'D1'},
            ],
            'remove': ['D99', 'D100'],
            'source_ts': 500,
        }
        req = DepartmentsSyncRequest.model_validate(raw)
        assert len(req.upsert) == 2
        assert req.upsert[0].ts == 10
        assert req.upsert[1].parent_external_id == 'D1'
        assert req.remove == ['D99', 'D100']
        assert req.source_ts == 500


class TestResponseShapes:

    def test_login_sync_response_fields(self):
        resp = LoginSyncResponse(user_id=7, leaf_tenant_id=15, token='xxx')
        assert resp.model_dump() == {
            'user_id': 7, 'leaf_tenant_id': 15, 'token': 'xxx',
        }

    def test_batch_result_defaults(self):
        r = BatchResult()
        assert r.applied_upsert == 0
        assert r.applied_remove == 0
        assert r.skipped_ts_conflict == 0
        assert r.orphan_triggered == []
        assert r.errors == []
