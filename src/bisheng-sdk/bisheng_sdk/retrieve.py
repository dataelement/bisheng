"""以**当前访问者**的身份检索知识——选错身份就是越权，这里把选择固定下来。

一行到位：

    from bisheng_sdk import retrieve

    result = retrieve.search("年假怎么休", knowledge_base_ids=[12])

**两把凭据，缺一不可**（F055 已落地的托管运行契约）：

* ``Authorization: Bearer <BISHENG_APP_TOKEN>`` —— 应用自身的运行期凭据，
  回答"这次调用来自哪个应用"，平台据此取出该应用**当前生效的能力声明白名单**；
* ``X-BiSheng-Access-Token: <本请求注入的访问者凭据>`` —— 回答"这次调用是为谁做
  的"，平台据此确立访问用户。

两者都在托管容器里，但角色不能互换：只带应用凭据的检索会被平台以「无访问用户」
拒绝（**没有 owner 可以兜底**），只带访问者凭据则不认识这个应用。访问者凭据只从
**请求上下文**取，绝不从进程级环境变量取——否则后台任务会"顺手"拿到一把凭据，
越权路径就在一个默认参数之外。

没有 ``as_user``、没有任何指定他人身份的参数：那是 `--as` 的代码翻版。

可及范围由平台决定，SDK 不参与：托管期 = 应用当前生效声明的白名单 ∩ 访问用户
可见范围（文件级）；本地 `bisheng dev` 期 = 服务账号被显式授予的范围（无白名单）。
于是开发期只会"本地看得少"，不会"本地能跑、线上越权"。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from bisheng_sdk import _compat, _context, _env, _http
from bisheng_sdk.errors import AppCredentialMissingError, VisitorCredentialMissingError

__all__ = ("Chunk", "KnowledgeBaseFilter", "RetrieveResult", "asearch", "search")

#: F052 统一检索门面在开放面上的唯一路径（AC-11 / F052 AC-26）。
RETRIEVE_PATH = "/api/v2/filelib/retrieve"

#: 访问者凭据以头的形式随调用一起送出，头名与 app-proxy 注入给应用的那一个相同
#: （`open_api/domain/services/model_range_policy.py::ACCESS_TOKEN_HEADER`）。
ACCESS_TOKEN_HEADER = "X-BiSheng-Access-Token"


@dataclass(frozen=True)
class Chunk:
    """一个可引用溯源的片段。字段与门面出参一一对应，SDK 不增删。"""

    content: str
    knowledge_id: int
    document_id: int
    document_name: str
    chunk_index: int
    document_update_time: str = ""


@dataclass(frozen=True)
class RetrieveResult:
    chunks: list[Chunk] = field(default_factory=list)
    total: int = 0


@dataclass(frozen=True)
class KnowledgeBaseFilter:
    """按知识库的标签过滤。

    ``tag_match_mode`` 的合法值是 ``"ANY"``（服务端 `RetrieveFilters` 的字面量，
    大写）；``"ALL"`` 服务端尚未实现、会答 400——SDK 不替它翻译成 ``ANY``，
    那会返回**比你要的更宽**的结果集而无从察觉。
    """

    knowledge_base_id: int
    tags: Sequence[str] = ()
    tag_match_mode: str = "ANY"


def _credentials() -> tuple[str, str]:
    """(应用运行期凭据, 访问者凭据)。任一缺失都是明确、可区分的错误。"""
    visitor = _context.access_token()
    if not visitor:
        raise VisitorCredentialMissingError()
    app = _env.app_token()
    if not app:
        raise AppCredentialMissingError()
    return app, visitor


def _body(
    query: str,
    knowledge_base_ids: Sequence[int] | None,
    top_k: int,
    max_content: int,
    filters: Sequence[KnowledgeBaseFilter] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"query": query, "top_k": top_k, "max_content": max_content}
    if knowledge_base_ids is not None:
        # 服务端 schema 是 `extra="forbid"`，送 `null` 会 422；不指定就**省略该键**。
        body["knowledge_base_ids"] = [int(one) for one in knowledge_base_ids]
    if filters:
        body["filters"] = {
            "knowledge_base_filters": [
                {
                    "knowledge_base_id": int(one.knowledge_base_id),
                    "tags": list(one.tags),
                    "tag_match_mode": one.tag_match_mode,
                }
                for one in filters
            ]
        }
    return body


def _result(data: Any) -> RetrieveResult:
    payload = data if isinstance(data, dict) else {}
    rows = payload.get("chunks") or []
    chunks = [
        Chunk(
            content=str(row.get("content") or ""),
            knowledge_id=int(row.get("knowledge_id") or 0),
            document_id=int(row.get("document_id") or 0),
            document_name=str(row.get("document_name") or ""),
            chunk_index=int(row.get("chunk_index") or 0),
            document_update_time=str(row.get("document_update_time") or ""),
        )
        for row in rows
        if isinstance(row, dict)
    ]
    total = payload.get("total")
    return RetrieveResult(chunks=chunks, total=int(total) if isinstance(total, int) else len(chunks))


def search(
    query: str,
    *,
    knowledge_base_ids: Sequence[int] | None = None,
    top_k: int = 10,
    max_content: int = 15000,
    filters: Sequence[KnowledgeBaseFilter] | None = None,
) -> RetrieveResult:
    """检索，以当前访问者的身份。

    失败一律抛异常、彼此可区分（没有访问者凭据 / 凭据被拒 / 缺权限位 / 目标不可及
    / 能力已收回 / 权限评估失败 / 版本不兼容 / 平台不可达），**绝不**返回空集
    当作成功，也绝不按白名单全量放行。
    """
    app_token, visitor_token = _credentials()
    base = _env.platform_api_base()
    _compat.ensure_compatible(base)
    resp = _http.request(
        "retrieve",
        "POST",
        RETRIEVE_PATH,
        base_url=base,
        bearer=app_token,
        headers={ACCESS_TOKEN_HEADER: visitor_token},
        json=_body(query, knowledge_base_ids, top_k, max_content, filters),
    )
    return _result(_http.parse_envelope(resp))


async def asearch(
    query: str,
    *,
    knowledge_base_ids: Sequence[int] | None = None,
    top_k: int = 10,
    max_content: int = 15000,
    filters: Sequence[KnowledgeBaseFilter] | None = None,
) -> RetrieveResult:
    """:func:`search` 的异步孪生：同一套入参、同一套错误、同一条码路。"""
    app_token, visitor_token = _credentials()
    base = _env.platform_api_base()
    await _compat.aensure_compatible(base)
    resp = await _http.arequest(
        "retrieve",
        "POST",
        RETRIEVE_PATH,
        base_url=base,
        bearer=app_token,
        headers={ACCESS_TOKEN_HEADER: visitor_token},
        json=_body(query, knowledge_base_ids, top_k, max_content, filters),
    )
    return _result(_http.parse_envelope(resp))
