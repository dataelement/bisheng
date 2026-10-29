"""本地毕昇 :7860 上的异常文件筛选。库是本机配置里的 171 中间件。

搜索框不单独打接口。用例按页面行为：先在选项里用关键字命中一条，再拿全称请求列表。
"""

# ruff: noqa: RUF002

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from test.knowledge.test_abnormal_upload_flow import (
    PREFIX,
    _insert_file,
    _insert_space,
    _insert_user,
    _set_update_time,
)

API = "http://127.0.0.1:7860"


def _search_hit(options: list[str], typed: str) -> str:
    """下拉搜索框：按输入过滤选项，必须只剩一条，再拿这条全称去查。"""
    needle = typed.casefold()
    hits = [name for name in options if needle in name.casefold()]
    assert len(hits) == 1, (typed, hits)
    return hits[0]


async def _insert_department(
    session: AsyncSession,
    *,
    dept_key: str,
    name: str,
    parent_id: int | None,
    org_level: str | None,
) -> int:
    await session.execute(
        text(
            """
            INSERT INTO department
              (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
            VALUES
              (:dept_id, :name, :parent_id, 1, '/', 'active', 'local', :org_level, 0)
            """
        ),
        {"dept_id": dept_key, "name": name, "parent_id": parent_id, "org_level": org_level},
    )
    await session.commit()
    return int(
        (await session.execute(text("SELECT id FROM department WHERE dept_id = :d"), {"d": dept_key})).scalar_one()
    )


async def _set_path(session: AsyncSession, department_id: int, path: str) -> None:
    await session.execute(
        text("UPDATE department SET path = :path WHERE id = :id"),
        {"path": path, "id": department_id},
    )
    await session.commit()


async def _bind_primary(session: AsyncSession, user_id: int, department_id: int) -> None:
    await session.execute(
        text("INSERT INTO user_department (user_id, department_id, is_primary) VALUES (:u, :d, 1)"),
        {"u": user_id, "d": department_id},
    )
    await session.commit()


async def _set_org(session: AsyncSession, file_id: int, organization_id: int | None) -> None:
    await session.execute(
        text("UPDATE knowledgefile SET belonging_organization_id = :org WHERE id = :id"),
        {"org": organization_id, "id": file_id},
    )
    await session.commit()


async def _cleanup_filter(engine, *, user_ids, space_ids, file_ids, department_ids) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if file_ids:
            ids = ",".join(str(int(i)) for i in file_ids)
            await session.execute(text(f"DELETE FROM knowledgefile WHERE id IN ({ids})"))
        if space_ids:
            ids = ",".join(str(int(i)) for i in space_ids)
            await session.execute(text(f"DELETE FROM knowledge_space_scope WHERE space_id IN ({ids})"))
            await session.execute(text(f"DELETE FROM knowledge WHERE id IN ({ids})"))
        if user_ids:
            ids = ",".join(str(int(i)) for i in user_ids)
            await session.execute(text(f"DELETE FROM user_department WHERE user_id IN ({ids})"))
            await session.execute(text(f"DELETE FROM userrole WHERE user_id IN ({ids})"))
            await session.execute(text(f"DELETE FROM user WHERE user_id IN ({ids})"))
        if department_ids:
            ids = ",".join(str(int(i)) for i in department_ids)
            await session.execute(text(f"DELETE FROM department WHERE id IN ({ids})"))
        await session.commit()


def _token_for(user_id: int, user_name: str, token_version: int) -> str:
    import json
    from datetime import datetime, timezone

    import jwt

    from bisheng.core.cache.redis_manager import get_redis_client_sync
    from bisheng.core.config.settings import Settings

    secret = Settings.model_fields["jwt_secret"].default
    payload = {
        "sub": json.dumps(
            {
                "user_id": user_id,
                "user_name": user_name,
                "tenant_id": 1,
                "token_version": token_version,
            }
        ),
        "exp": int(datetime.now(timezone.utc).timestamp()) + 86400,
        "iss": "bisheng",
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    get_redis_client_sync().set(f"user_current_session:{user_id}", token, 3600)
    return token


async def _names(client: httpx.Client, **params) -> set[str]:
    response = client.get(PREFIX, params={"page": 1, "page_size": 50, **params})
    body = response.json()
    assert response.status_code == 200, body
    assert body["status_code"] == 200, body
    return {item["file_name"] for item in body["data"]["data"]}


@pytest.mark.asyncio
async def test_abnormal_upload_filter_combinations_on_local_api(flow_env):
    health = httpx.get(f"{API}/health", timeout=5)
    assert health.status_code == 200, "本地毕昇 7860 没起来"

    engine = flow_env
    token = uuid.uuid4().hex[:8]
    company_name = f"甲公司{token}"
    dept_name = f"甲设备部{token}"
    office_name = f"甲点检科{token}"
    other_company = f"乙公司{token}"
    other_dept = f"乙炼钢部{token}"
    unlabeled_name = f"未标部门{token}"
    library_a = f"甲库{token}"
    library_b = f"乙库{token}"
    person_a = f"张筛选{token}"
    person_b = f"李筛选{token}"
    person_c = f"无组织{token}"
    operator_name = f"筛运营{token}"

    department_ids: list[int] = []
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            company_id = await _insert_department(
                session, dept_key=f"flt-co-{token}", name=company_name, parent_id=None, org_level="company"
            )
            await _set_path(session, company_id, f"/{company_id}/")
            dept_id = await _insert_department(
                session, dept_key=f"flt-dp-{token}", name=dept_name, parent_id=company_id, org_level="dept"
            )
            await _set_path(session, dept_id, f"/{company_id}/{dept_id}/")
            office_id = await _insert_department(
                session, dept_key=f"flt-of-{token}", name=office_name, parent_id=dept_id, org_level="office"
            )
            await _set_path(session, office_id, f"/{company_id}/{dept_id}/{office_id}/")
            other_company_id = await _insert_department(
                session, dept_key=f"flt-oc-{token}", name=other_company, parent_id=None, org_level="company"
            )
            await _set_path(session, other_company_id, f"/{other_company_id}/")
            other_dept_id = await _insert_department(
                session, dept_key=f"flt-od-{token}", name=other_dept, parent_id=other_company_id, org_level="dept"
            )
            await _set_path(session, other_dept_id, f"/{other_company_id}/{other_dept_id}/")
            unlabeled_id = await _insert_department(
                session, dept_key=f"flt-ul-{token}", name=unlabeled_name, parent_id=company_id, org_level=None
            )
            await _set_path(session, unlabeled_id, f"/{company_id}/{unlabeled_id}/")
            department_ids.extend([company_id, dept_id, office_id, other_company_id, other_dept_id, unlabeled_id])

            user_a = await _insert_user(session, person_a)
            user_b = await _insert_user(session, person_b)
            user_c = await _insert_user(session, person_c)
            operator = await _insert_user(session, operator_name)
            user_ids.extend([user_a, user_b, user_c, operator])
            await _bind_primary(session, user_a, office_id)
            await _bind_primary(session, user_b, other_dept_id)
            role_id = (
                await session.execute(text("SELECT id FROM role WHERE role_name = '平台管理员' LIMIT 1"))
            ).scalar_one()
            await session.execute(
                text("INSERT INTO userrole (user_id, role_id, tenant_id) VALUES (:u, :r, 1)"),
                {"u": operator, "r": int(role_id)},
            )
            await session.commit()

            space_a = await _insert_space(session, name=library_a, level="department")
            space_b = await _insert_space(session, name=library_b, level="personal")
            space_ids.extend([space_a, space_b])

            failed = await _insert_file(
                session,
                user_id=user_a,
                user_name=person_a,
                space_id=space_a,
                file_name=f"甲失败{token}.pdf",
                status=3,
            )
            timeout = await _insert_file(
                session,
                user_id=user_a,
                user_name=person_a,
                space_id=space_a,
                file_name=f"甲超时{token}.pdf",
                status=6,
            )
            violation = await _insert_file(
                session,
                user_id=user_a,
                user_name=person_a,
                space_id=space_b,
                file_name=f"甲违规{token}.pdf",
                status=7,
            )
            fallback = await _insert_file(
                session,
                user_id=user_b,
                user_name=person_b,
                space_id=space_b,
                file_name=f"乙失败{token}.pdf",
                status=3,
            )
            no_org = await _insert_file(
                session,
                user_id=user_c,
                user_name=person_c,
                space_id=space_a,
                file_name=f"无组织{token}.pdf",
                status=3,
            )
            unlabeled = await _insert_file(
                session,
                user_id=user_a,
                user_name=person_a,
                space_id=space_a,
                file_name=f"未打标{token}.pdf",
                status=3,
            )
            success = await _insert_file(
                session,
                user_id=user_a,
                user_name=person_a,
                space_id=space_a,
                file_name=f"成功{token}.pdf",
                status=2,
            )
            shared = await _insert_file(
                session,
                user_id=user_a,
                user_name=person_a,
                space_id=space_a,
                file_name=f"分享{token}.pdf",
                status=3,
                entry_type="share",
            )
            file_ids.extend([failed, timeout, violation, fallback, no_org, unlabeled, success, shared])
            await _set_org(session, failed, office_id)
            await _set_org(session, timeout, office_id)
            await _set_org(session, violation, office_id)
            await _set_org(session, unlabeled, unlabeled_id)
            await _set_update_time(session, failed, "2020-03-01 08:00:00")
            await _set_update_time(session, timeout, "2020-03-15 23:00:00")
            await _set_update_time(session, violation, "2020-04-01 10:00:00")
            await _set_update_time(session, fallback, "2020-03-10 12:00:00")
            await _set_update_time(session, no_org, "2020-03-20 12:00:00")
            await _set_update_time(session, unlabeled, "2020-03-01 09:00:00")
            version = int(
                (
                    await session.execute(
                        text("SELECT token_version FROM user WHERE user_id = :id"),
                        {"id": operator},
                    )
                ).scalar_one()
                or 0
            )

        access = _token_for(operator, operator_name, version)
        from pathlib import Path

        Path("/tmp/abn-token.txt").write_text(access)
        anchor = {"keyword": token}
        with httpx.Client(
            base_url=API,
            headers={"Cookie": f"access_token_cookie={access}"},
            timeout=30,
        ) as client:
            raw = client.get(f"{PREFIX}/org-options")
            options = raw.json() if raw.headers.get("content-type", "").startswith("application/json") else {}
            assert raw.status_code == 200 and options.get("status_code") == 200, raw.text[:400]
            data = options["data"]
            for bucket, expected in (
                ("companies", company_name),
                ("departments", dept_name),
                ("offices", office_name),
                ("knowledges", library_a),
                ("uploaders", person_a),
            ):
                assert expected in data[bucket], (bucket, expected)

            visible = await _names(client, **anchor)
            assert visible == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"甲违规{token}.pdf",
                f"乙失败{token}.pdf",
                f"无组织{token}.pdf",
                f"未打标{token}.pdf",
            }

            listed = client.get(PREFIX, params={"page": 1, "page_size": 50, **anchor}).json()["data"]["data"]
            by_name = {item["file_name"]: item for item in listed}
            assert by_name[f"甲失败{token}.pdf"]["company_name"] == company_name
            assert by_name[f"甲失败{token}.pdf"]["department_name"] == dept_name
            assert by_name[f"甲失败{token}.pdf"]["office_name"] == office_name
            assert by_name[f"乙失败{token}.pdf"]["company_name"] == other_company
            assert by_name[f"乙失败{token}.pdf"]["department_name"] == other_dept
            assert by_name[f"乙失败{token}.pdf"]["office_name"] == ""
            assert by_name[f"无组织{token}.pdf"]["company_name"] == ""
            assert by_name[f"未打标{token}.pdf"]["company_name"] == company_name
            assert by_name[f"未打标{token}.pdf"]["department_name"] == unlabeled_name
            assert by_name[f"未打标{token}.pdf"]["office_name"] == ""

            assert await _names(client, **anchor, status=3) == {
                f"甲失败{token}.pdf",
                f"乙失败{token}.pdf",
                f"无组织{token}.pdf",
                f"未打标{token}.pdf",
            }
            assert await _names(client, **anchor, status=6) == {f"甲超时{token}.pdf"}
            assert await _names(client, **anchor, status=7) == {f"甲违规{token}.pdf"}
            assert await _names(client, **anchor, space_level="department") == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"无组织{token}.pdf",
                f"未打标{token}.pdf",
            }
            assert await _names(client, **anchor, space_level="personal") == {
                f"甲违规{token}.pdf",
                f"乙失败{token}.pdf",
            }

            knowledge_hit = _search_hit(data["knowledges"], f"甲库{token}")
            ambiguous = [name for name in data["uploaders"] if f"筛选{token}".casefold() in name.casefold()]
            assert set(ambiguous) == {person_a, person_b}
            uploader_hit = _search_hit(data["uploaders"], person_a)
            company_hit = _search_hit(data["companies"], f"甲公司{token}")
            department_hit = _search_hit(data["departments"], f"设备部{token}")
            office_hit = _search_hit(data["offices"], f"点检科{token}")
            assert await _names(client, knowledge_name=knowledge_hit) == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"无组织{token}.pdf",
                f"未打标{token}.pdf",
            }
            assert await _names(client, **anchor, uploader_name=uploader_hit) == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"甲违规{token}.pdf",
                f"未打标{token}.pdf",
            }
            assert await _names(client, **anchor, uploader_company=company_hit) == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"甲违规{token}.pdf",
                f"未打标{token}.pdf",
            }
            assert await _names(client, **anchor, uploader_department=department_hit) == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"甲违规{token}.pdf",
            }
            assert await _names(client, **anchor, uploader_office=office_hit) == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"甲违规{token}.pdf",
            }
            assert await _names(
                client,
                **anchor,
                uploader_company=_search_hit(data["companies"], f"乙公司{token}"),
            ) == {f"乙失败{token}.pdf"}

            combined = await _names(
                client,
                status=3,
                space_level="department",
                knowledge_name=library_a,
                uploader_name=person_a,
                uploader_company=company_name,
                uploader_department=dept_name,
                uploader_office=office_name,
                update_time_from="2020-03-01",
                update_time_to="2020-03-01",
            )
            assert combined == {f"甲失败{token}.pdf"}

            assert (
                await _names(
                    client,
                    **anchor,
                    uploader_company=company_name,
                    uploader_department=other_dept,
                )
                == set()
            )
            assert await _names(
                client,
                **anchor,
                update_time_from="2020-03-01",
                update_time_to="2020-03-15",
            ) == {
                f"甲失败{token}.pdf",
                f"甲超时{token}.pdf",
                f"乙失败{token}.pdf",
                f"未打标{token}.pdf",
            }
            assert await _names(
                client,
                **anchor,
                update_time_from="2020-03-15",
                update_time_to="2020-03-15",
            ) == {f"甲超时{token}.pdf"}
            assert (
                await _names(
                    client,
                    **anchor,
                    update_time_from="2020-03-16",
                    update_time_to="2020-03-19",
                )
                == set()
            )
            assert await _names(client, **anchor, uploader_company="不存在的公司") == set()
            assert [name for name in data["knowledges"] if "不存在的库" in name] == []

            bad_status = client.get(PREFIX, params={**anchor, "status": 2})
            bad_level = client.get(PREFIX, params={**anchor, "space_level": "nope"})
            bad_date = client.get(
                PREFIX,
                params={**anchor, "update_time_from": "2020-04-02", "update_time_to": "2020-03-01"},
            )
            bad_page = client.get(PREFIX, params={"page": 0, "page_size": 20, **anchor})
            bad_org = client.get(PREFIX, params={**anchor, "uploader_company": "公" * 129})
            for response in (bad_status, bad_level, bad_date, bad_page, bad_org):
                assert response.status_code == 200
                assert response.json()["status_code"] == 422, response.json()

            page = client.get(PREFIX, params={"page": 1, "page_size": 1, **anchor})
            page_body = page.json()["data"]
            assert page_body["total"] == 6
            assert len(page_body["data"]) == 1
    finally:
        await _cleanup_filter(
            engine,
            user_ids=user_ids,
            space_ids=space_ids,
            file_ids=file_ids,
            department_ids=department_ids,
        )
        if user_ids:
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            for user_id in user_ids:
                get_redis_client_sync().delete(f"user_current_session:{user_id}")
