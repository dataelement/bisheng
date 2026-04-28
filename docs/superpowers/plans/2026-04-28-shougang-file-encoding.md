# 首钢文件编码功能 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Per user policy: do NOT auto-commit.** Each task lists a commit command at the end — surface the command to the user and let them run it (or approve it explicitly).

**Goal:** 在 Bisheng 客户端知识空间增加「文件编码」(file encoding) 功能 — 启用 shougang 配置后,上传文件时由 LLM 自动生成 `GF-ZD-SC-202604-00001` 格式编码,前端显示并支持空间 owner/admin 编辑。

**Architecture:** 后端 (1) 新增 `ShougangConf` DB 配置 + getter; (2) `KnowledgeFile` 加 `file_encoding` 列; (3) 在解析 Celery 任务链 `_init_common_transformers` 中插入 `FileEncodingTransformer`,该 transformer 复用 `chat_title_llm` 做分类、按 `create_time` 算月度序列号; (4) 新增 PUT 编辑端点 + `bsConfig` 暴露开关。前端 (5) FileTable 加列 + 编辑弹窗,通过 `useGetBsConfig().shougang.enabled` 条件渲染。

**Tech Stack:** Python 3.10+, FastAPI, SQLModel + Alembic, LangChain `BaseDocumentTransformer`, Celery; React 18 + Vite 6 + TypeScript + Recoil + react-query v5 + Radix UI + react-i18next.

**Spec reference:** `/Users/shanghang/dataelem/bisheng/docs/superpowers/specs/2026-04-28-shougang-file-encoding-design.md`

---

## File Structure

### Backend new files
- `src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py` — Transformer 主体
- `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f033_add_file_encoding.py` — DB 迁移
- `src/backend/test/unit/test_file_encoding_transformer.py` — Transformer 单测
- `src/backend/test/unit/test_shougang_conf.py` — 配置 getter 单测
- `src/backend/test/integration/test_update_file_encoding_endpoint.py` — 端点集成测

### Backend modified files
- `src/backend/bisheng/core/config/settings.py` — 加 `ShougangConf`
- `src/backend/bisheng/common/services/config_service.py` — 加 `aget_shougang_conf`
- `src/backend/bisheng/knowledge/domain/models/knowledge_file.py` — 加 `file_encoding` 列
- `src/backend/bisheng/knowledge/rag/knowledge_file_pipeline.py` — 注册新 transformer
- `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py` — 新 PUT 端点
- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` — 加 `update_file_encoding`
- `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py` — 加 `FileEncodingUpdateReq`
- `src/backend/bisheng/workstation/api/endpoints/config.py` — `bsConfig` 暴露 shougang

### Frontend new files
- `src/frontend/client/src/pages/knowledge/SpaceDetail/EditEncodingModal.tsx` — 编辑弹窗

### Frontend modified files
- `src/frontend/client/src/api/knowledge.ts` — `KnowledgeFile.fileEncoding` + `updateFileEncoding` API
- `src/frontend/client/src/types/chat/config.ts` — `BsConfig.shougang`
- `src/frontend/client/src/hooks/queries/endpoints/queries.ts` — `useGetBsConfig` 默认值
- `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx` — 加列
- `src/frontend/client/src/locales/{en,zh-Hans,ja}/translation.json` — i18n keys

---

## Task 1: 添加 `ShougangConf` pydantic model

**Files:**
- Modify: `src/backend/bisheng/core/config/settings.py` (insert after `DailyChatConf`,~line 297)

- [ ] **Step 1: 在 settings.py 末尾的 DailyChatConf 类后插入新 model**

打开 `src/backend/bisheng/core/config/settings.py`,在 `DailyChatConf` 类的最后一个 `_coerce_history_max_tokens` validator 之后(约 line 297),插入:

```python
class ShougangConf(BaseModel):
    """ Shougang (首钢) deployment-specific configuration.

    Stored in DB config under key `shougang`. When the block exists and
    `prefix` is set, the file-encoding feature is considered enabled.
    """
    prefix: Optional[str] = Field(
        default=None,
        description='File-encoding prefix, e.g. "GF". Empty/None disables the feature.',
    )
    # The two below are reserved for other shougang sub-features and are not
    # consumed by the file-encoding pipeline. Kept here so the model accepts them.
    deployment_label: Optional[str] = Field(default=None)
    portal_admin_url: Optional[str] = Field(default=None)

    @property
    def enabled(self) -> bool:
        return bool(self.prefix)
```

确认 `Optional` 已在文件顶部 import(应该已经有,因为 `DailyChatConf` 没用但其他类用)。如果 `Optional` 不在 import 列表,在 `from typing import` 那行加上。

- [ ] **Step 2: 提交**

```bash
git add src/backend/bisheng/core/config/settings.py
git commit -m "feat(shougang): add ShougangConf pydantic model"
```

---

## Task 2: 添加 `aget_shougang_conf` getter (TDD)

**Files:**
- Create: `src/backend/test/unit/test_shougang_conf.py`
- Modify: `src/backend/bisheng/common/services/config_service.py` (insert after `aget_daily_chat_conf`,~line 226)

- [ ] **Step 1: 写 failing test**

创建 `src/backend/test/unit/test_shougang_conf.py`:

```python
"""Unit tests for ShougangConf and ConfigService.aget_shougang_conf."""
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.core.config.settings import ShougangConf
from bisheng.common.services.config_service import ConfigService


def test_shougang_conf_disabled_when_prefix_empty():
    conf = ShougangConf()
    assert conf.enabled is False
    conf2 = ShougangConf(prefix="")
    assert conf2.enabled is False


def test_shougang_conf_enabled_with_prefix():
    conf = ShougangConf(prefix="GF")
    assert conf.enabled is True
    assert conf.prefix == "GF"


def test_shougang_conf_accepts_unused_fields():
    conf = ShougangConf(
        prefix="GF",
        deployment_label="首钢",
        portal_admin_url="/portal-admin/",
    )
    assert conf.deployment_label == "首钢"
    assert conf.portal_admin_url == "/portal-admin/"


@pytest.mark.asyncio
async def test_aget_shougang_conf_returns_default_when_block_missing():
    svc = ConfigService.__new__(ConfigService)
    with patch.object(svc, "aget_all_config", AsyncMock(return_value={})):
        conf = await svc.aget_shougang_conf()
    assert conf.enabled is False
    assert conf.prefix is None


@pytest.mark.asyncio
async def test_aget_shougang_conf_returns_parsed_block():
    svc = ConfigService.__new__(ConfigService)
    cfg = {"shougang": {"prefix": "GF", "deployment_label": "首钢"}}
    with patch.object(svc, "aget_all_config", AsyncMock(return_value=cfg)):
        conf = await svc.aget_shougang_conf()
    assert conf.enabled is True
    assert conf.prefix == "GF"
    assert conf.deployment_label == "首钢"


@pytest.mark.asyncio
async def test_aget_shougang_conf_swallows_exceptions():
    svc = ConfigService.__new__(ConfigService)
    with patch.object(svc, "aget_all_config", AsyncMock(side_effect=RuntimeError("redis down"))):
        conf = await svc.aget_shougang_conf()
    assert conf.enabled is False
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/pytest test/unit/test_shougang_conf.py -v
```
Expected: 后两个测试失败(`AttributeError: ... has no attribute 'aget_shougang_conf'`)

- [ ] **Step 3: 在 ConfigService 中实现 getter**

打开 `src/backend/bisheng/common/services/config_service.py`,在 `aget_daily_chat_conf` 方法之后(约 line 226 之后,`return DailyChatConf()` 之后),插入:

```python
    async def aget_shougang_conf(self) -> 'ShougangConf':
        """Get shougang deployment config from DB. Returns default (disabled) on miss/error."""
        from bisheng.core.config.settings import ShougangConf
        try:
            all_config = await self.aget_all_config()
            return ShougangConf(**(all_config.get('shougang', {}) or {}))
        except Exception as e:
            logger.warning(f'Failed to load shougang conf, using defaults: {e}')
            return ShougangConf()
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
.venv/bin/pytest test/unit/test_shougang_conf.py -v
```
Expected: 全部 6 个测试 PASS

- [ ] **Step 5: 提交**

```bash
git add src/backend/bisheng/common/services/config_service.py \
        src/backend/test/unit/test_shougang_conf.py
git commit -m "feat(shougang): add aget_shougang_conf with tests"
```

---

## Task 3: 在 KnowledgeFile model 加 `file_encoding` 列

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/models/knowledge_file.py`(`KnowledgeFileBase` 类,约 line 78 后)

- [ ] **Step 1: 添加列定义**

打开 `src/backend/bisheng/knowledge/domain/models/knowledge_file.py`,在 `KnowledgeFileBase` 类中,**在 `remark` 字段定义之后、`updater_id` 之前**(约 line 78–79 之间),插入:

```python
    file_encoding: Optional[str] = Field(
        default=None,
        max_length=64,
        sa_column=Column(String(64), nullable=True),
        description='File encoding for shougang deployment, e.g. "GF-ZD-SC-202604-00001". '
                    'NULL when shougang is disabled or encoding generation has not run yet.',
    )
```

确认 `String` 已在文件顶部 `from sqlalchemy import ...` 中(应该已经有 String 导入)。

- [ ] **Step 2: 检查 SQLModel 推断的 Python 类型**

读取修改后的 `KnowledgeFileBase`,确认 `file_encoding` 出现在响应序列化的字段中。运行:

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/python -c "
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
print('file_encoding' in KnowledgeFile.model_fields)
"
```
Expected: `True`

- [ ] **Step 3: 提交**

```bash
git add src/backend/bisheng/knowledge/domain/models/knowledge_file.py
git commit -m "feat(shougang): add file_encoding column to KnowledgeFile"
```

---

## Task 4: 创建 alembic 迁移脚本

**Files:**
- Create: `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f033_add_file_encoding.py`

- [ ] **Step 1: 找到当前 head revision**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/alembic heads
```
记下输出的 revision id(预期是 `v2_5_1_f032_workbench_subscription_web_menu_backfill` 对应的 revision)。

- [ ] **Step 2: 创建迁移文件**

创建 `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f033_add_file_encoding.py`:

```python
"""Add file_encoding column to knowledge_file (shougang feature, F033)

Revision ID: v2_5_1_f033
Revises: v2_5_1_f032   # ⚠ 实际填入 Step 1 的输出
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'v2_5_1_f033'
down_revision = 'v2_5_1_f032'  # ⚠ 实际填入 Step 1 的输出
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists('knowledge_file', 'file_encoding'):
        op.add_column(
            'knowledge_file',
            sa.Column(
                'file_encoding',
                sa.String(length=64),
                nullable=True,
                comment='File encoding for shougang deployment, e.g. GF-ZD-SC-202604-00001 (F033)',
            ),
        )


def downgrade() -> None:
    if _column_exists('knowledge_file', 'file_encoding'):
        op.drop_column('knowledge_file', 'file_encoding')
```

⚠ **重要**:把 `down_revision = 'v2_5_1_f032'` 替换为 Step 1 输出的实际 revision id。

- [ ] **Step 3: 在测试库运行迁移**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/alembic upgrade head
```
Expected: 输出 `Running upgrade ... -> v2_5_1_f033, Add file_encoding column...`

验证列已加:

```bash
.venv/bin/python -c "
from bisheng.core.database.async_engine import async_engine
from sqlalchemy import inspect
import asyncio

async def check():
    async with async_engine.connect() as conn:
        def _i(c): return inspect(c)
        insp = await conn.run_sync(_i)
        cols = [c['name'] for c in insp.get_columns('knowledge_file')]
        print('file_encoding' in cols)

asyncio.run(check())
"
```
Expected: `True`

- [ ] **Step 4: 验证 downgrade 可回滚**

```bash
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
```
Expected: 两条命令都成功,回滚再升级后列还在。

- [ ] **Step 5: 提交**

```bash
git add src/backend/bisheng/core/database/alembic/versions/v2_5_1_f033_add_file_encoding.py
git commit -m "feat(shougang): alembic migration for file_encoding column"
```

---

## Task 5: 写 `FileEncodingTransformer` 的纯函数单测(TDD,先写测试再实现)

**Files:**
- Create: `src/backend/test/unit/test_file_encoding_transformer.py`

- [ ] **Step 1: 写 failing tests(只覆盖纯函数:正则、月份、序列号封顶、配置 skip 决策)**

创建 `src/backend/test/unit/test_file_encoding_transformer.py`:

```python
"""Unit tests for FileEncodingTransformer pure logic."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.rag.pipeline.transformer.file_encoding import (
    FileEncodingTransformer,
    VALID_PATTERN,
    FALLBACK,
)


def test_valid_pattern_accepts_known_combinations():
    assert VALID_PATTERN.match("ZD-SC")
    assert VALID_PATTERN.match("JSTZ-XX")
    assert VALID_PATTERN.match("HYJY-AQ")
    assert VALID_PATTERN.match("JSXY-NY")


def test_valid_pattern_rejects_invalid():
    assert not VALID_PATTERN.match("ZD-OT")          # OT not in business domains
    assert not VALID_PATTERN.match("OT-SC")          # OT not in doc types
    assert not VALID_PATTERN.match("zd-sc")          # lowercase
    assert not VALID_PATTERN.match("ZD - SC")        # whitespace
    assert not VALID_PATTERN.match("ZD-SC-extra")    # trailing
    assert not VALID_PATTERN.match("```ZD-SC```")    # markdown
    assert not VALID_PATTERN.match("")


def test_fallback_value():
    assert FALLBACK == "ZD-SC"


def test_compose_encoding_pads_seq():
    kf = SimpleNamespace(
        id=1,
        file_encoding=None,
        file_name="x.pdf",
        abstract="some abstract",
        create_time=datetime(2026, 4, 15, 10, 0, 0),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    assert t._compose_encoding("GF", "ZD-SC", datetime(2026, 4, 1), 7) == "GF-ZD-SC-202604-00007"
    assert t._compose_encoding("GF", "JSTZ-XX", datetime(2026, 12, 31), 99999) == "GF-JSTZ-XX-202612-99999"
    assert t._compose_encoding("GF", "ZD-SC", datetime(2026, 1, 5), 1) == "GF-ZD-SC-202601-00001"


def test_seq_capped_at_99999():
    kf = SimpleNamespace(
        id=1,
        file_encoding=None,
        file_name="x.pdf",
        abstract="x",
        create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    assert t._cap_seq(0) == 1
    assert t._cap_seq(1) == 1
    assert t._cap_seq(99999) == 99999
    assert t._cap_seq(100000) == 99999
    assert t._cap_seq(500000) == 99999


def test_month_window():
    """Returns [month_start, month_end) as half-open interval."""
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        create_time=datetime(2026, 4, 15, 10, 30, 0),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    start, end = t._month_window()
    assert start == datetime(2026, 4, 1, 0, 0, 0, 0)
    assert end == datetime(2026, 5, 1, 0, 0, 0, 0)


def test_month_window_december_rolls_over():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        create_time=datetime(2026, 12, 31, 23, 59, 59),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    start, end = t._month_window()
    assert start == datetime(2026, 12, 1)
    assert end == datetime(2027, 1, 1)


@pytest.mark.asyncio
async def test_transform_skips_when_shougang_disabled():
    kf = SimpleNamespace(
        id=1, file_encoding=None, file_name="x", abstract="x",
        create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    fake_conf = SimpleNamespace(enabled=False, prefix=None)
    with patch(
        'bisheng.knowledge.rag.pipeline.transformer.file_encoding.bisheng_settings.aget_shougang_conf',
        AsyncMock(return_value=fake_conf),
    ):
        await t.atransform_documents([])
    assert kf.file_encoding is None


@pytest.mark.asyncio
async def test_transform_skips_when_encoding_already_present():
    kf = SimpleNamespace(
        id=1, file_encoding="GF-ZD-SC-202603-00001", file_name="x", abstract="x",
        create_time=datetime(2026, 4, 15),
    )
    t = FileEncodingTransformer(invoke_user_id=42, knowledge_file=kf)
    fake_conf = SimpleNamespace(enabled=True, prefix="GF")
    with patch(
        'bisheng.knowledge.rag.pipeline.transformer.file_encoding.bisheng_settings.aget_shougang_conf',
        AsyncMock(return_value=fake_conf),
    ):
        await t.atransform_documents([])
    # 不变
    assert kf.file_encoding == "GF-ZD-SC-202603-00001"
```

- [ ] **Step 2: 运行测试,确认全部失败(模块不存在)**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/pytest test/unit/test_file_encoding_transformer.py -v
```
Expected: ImportError 或 ModuleNotFoundError

---

## Task 6: 实现 `FileEncodingTransformer`

**Files:**
- Create: `src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py`

- [ ] **Step 0: 确认 pipeline 调用 sync 还是 async transform**

`langchain_core.documents.BaseDocumentTransformer` 同时支持 `transform_documents`(sync) 和 `atransform_documents`(async)。**实现前必须确认现有 pipeline 怎么调用 transformers**。

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
grep -rn "transform_documents\|atransform_documents" \
  bisheng/knowledge/rag/ | grep -v __pycache__ | grep -v test
```

并且看一眼现有 `AbstractTransformer.transform_documents` 内部如何处理 LLM 调用(它的 LLM 是 async,但 transform 是 sync — 一定有处理方式,比如 `asyncio.run` 或同步 LLM client)。Step 1 的实现需要**镜像**现有模式。

如果 pipeline 调用 sync `transform_documents`:把 Step 1 代码中的 `atransform_documents` 改名为 `transform_documents`,把方法体顶部加 `import asyncio` 然后用 `asyncio.run(...)` 包住整个 async 逻辑(或者拆出一个 helper async 方法)。如果 pipeline 调用 async `atransform_documents`,Step 1 代码可直接使用。

- [ ] **Step 1: 创建 transformer 文件**

创建 `src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py`:

```python
"""FileEncodingTransformer — generates a standardized file encoding for
shougang deployments. Inserted into the common transformer chain after
AbstractTransformer so the file's abstract is available for LLM classification.

Encoding format: PREFIX-DOCTYPE-DOMAIN-YYYYMM-NNNNN
Example: GF-ZD-SC-202604-00001
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger
from sqlalchemy import func, select

from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.database.async_engine import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.services.llm import LLMService
from bisheng.utils.constants import ApplicationTypeEnum

CLASSIFY_PROMPT = """# 角色
你是一个企业文件编码分类助手。你的任务是根据给定的文件标题、摘要或正文内容,为文件生成标准化的文件编码。

# 任务目标
你需要从文件内容中识别出:
1. 一个"文档类型"
2. 一个"业务域"

然后按以下格式输出文件编码:
文档类型编码-业务域编码
例如: ZD-SC

# 编码规则
## 一、文档类型(必须且只能从以下枚举中选择一个)
- 制度 = ZD
- 办法 = BF
- 法律 = FL
- 法规 = FG
- 技术通知单 = JSTZ
- 会议纪要 = HYJY
- 安全案例 = AQAL
- 预案 = YA
- 合同 = HT
- 技术协议 = JSXY

## 二、业务域(必须且只能从以下枚举中选择一个)
- 生产 = SC
- 投资 = TZ
- 研发 = YF
- 采购 = CG
- 营销 = YX
- 财务 = CW
- 设备 = SB
- 安全 = AQ
- 环保 = HB
- 质量 = ZL
- 人力 = RL
- 信息 = XX
- 能源 = NY
- 管理 = GL

# 判定原则
## 1. 总体要求
- 必须先判断"文档类型",再判断"业务域"。
- 只能使用上述枚举值,不允许输出未定义的类型、业务域或编码。
- 不允许根据个人理解自造缩写。

## 2. 输出要求
- 只输出最终编码
- 不要输出解释
- 不要输出多余文字
- 输出格式必须严格为: XX-YY"""

VALID_PATTERN = re.compile(
    r'^(ZD|BF|FL|FG|JSTZ|HYJY|AQAL|YA|HT|JSXY)-'
    r'(SC|TZ|YF|CG|YX|CW|SB|AQ|HB|ZL|RL|XX|NY|GL)$'
)
FALLBACK = "ZD-SC"
SEQ_CAP = 99999


class FileEncodingTransformer(BaseDocumentTransformer):
    """Generate file_encoding using LLM classification + monthly sequence.

    Skips when shougang is disabled or knowledge_file already has an encoding
    (idempotent for retries).
    """

    def __init__(self, invoke_user_id: int, knowledge_file: KnowledgeFile) -> None:
        self.invoke_user_id = invoke_user_id
        self.knowledge_file = knowledge_file

    # langchain BaseDocumentTransformer requires sync transform_documents;
    # we call our async path through atransform_documents.
    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        return list(documents)

    async def atransform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        try:
            shougang_conf = await bisheng_settings.aget_shougang_conf()
            if not shougang_conf.enabled:
                return list(documents)

            if self.knowledge_file.file_encoding:
                return list(documents)

            type_business_code = await self._classify_with_llm()
            ym = self.knowledge_file.create_time.strftime("%Y%m")
            seq = await self._compute_seq()
            self.knowledge_file.file_encoding = self._compose_encoding(
                shougang_conf.prefix, type_business_code,
                self.knowledge_file.create_time, seq,
            )
            logger.info(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"ym={ym} seq={seq:05d} type_business={type_business_code} "
                f"encoding={self.knowledge_file.file_encoding}"
            )
        except Exception as e:
            # 整体失败也走兜底,占序列号(spec Q5)
            try:
                shougang_conf = await bisheng_settings.aget_shougang_conf()
                if shougang_conf.enabled and not self.knowledge_file.file_encoding:
                    seq = await self._compute_seq()
                    self.knowledge_file.file_encoding = self._compose_encoding(
                        shougang_conf.prefix, FALLBACK,
                        self.knowledge_file.create_time, seq,
                    )
                    logger.warning(
                        f"[shougang.encoding] file_id={self.knowledge_file.id} "
                        f"fallback used: transformer_error={e}"
                    )
            except Exception as inner:
                logger.error(
                    f"[shougang.encoding] file_id={self.knowledge_file.id} "
                    f"abandoned: outer={e} inner={inner}"
                )
        return list(documents)

    async def _classify_with_llm(self) -> str:
        try:
            llm_conf = await LLMService.get_workbench_llm()
            if (not llm_conf
                    or not llm_conf.chat_title_llm
                    or not llm_conf.chat_title_llm.id):
                logger.warning(
                    f"[shougang.encoding] file_id={self.knowledge_file.id} "
                    f"fallback: chat_title_llm_unset"
                )
                return FALLBACK

            llm = await LLMService.get_bisheng_llm(
                model_id=llm_conf.chat_title_llm.id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                app_name='shougang_file_encoding',
                app_type=ApplicationTypeEnum.DAILY_CHAT,
                user_id=self.invoke_user_id,
            )

            content = (
                f"标题: {self.knowledge_file.file_name}\n"
                f"摘要: {self.knowledge_file.abstract or ''}"
            )
            response = await llm.ainvoke([
                {"role": "system", "content": CLASSIFY_PROMPT},
                {"role": "user", "content": content},
            ])
            result = (response.content or "").strip()

            if VALID_PATTERN.match(result):
                return result
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"fallback: invalid_format raw={result!r}"
            )
            return FALLBACK
        except Exception as e:
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"fallback: llm_error {e}"
            )
            return FALLBACK

    def _month_window(self) -> tuple[datetime, datetime]:
        ct = self.knowledge_file.create_time
        start = ct.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end

    async def _compute_seq(self) -> int:
        start, end = self._month_window()
        async with get_async_db_session() as session:
            count = await session.scalar(
                select(func.count()).select_from(KnowledgeFile).where(
                    KnowledgeFile.create_time >= start,
                    KnowledgeFile.create_time < end,
                    KnowledgeFile.create_time <= self.knowledge_file.create_time,
                    KnowledgeFile.file_type == 1,  # 排除 folder
                )
            )
        return self._cap_seq(count or 0)

    @staticmethod
    def _cap_seq(count: int) -> int:
        if count < 1:
            return 1
        if count > SEQ_CAP:
            return SEQ_CAP
        return count

    @staticmethod
    def _compose_encoding(prefix: str, type_business: str,
                          create_time: datetime, seq: int) -> str:
        ym = create_time.strftime("%Y%m")
        return f"{prefix}-{type_business}-{ym}-{seq:05d}"
```

- [ ] **Step 2: 运行 Task 5 的测试,确认通过**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/pytest test/unit/test_file_encoding_transformer.py -v
```
Expected: 全部 8 个测试 PASS

- [ ] **Step 3: 提交**

```bash
git add src/backend/bisheng/knowledge/rag/pipeline/transformer/file_encoding.py \
        src/backend/test/unit/test_file_encoding_transformer.py
git commit -m "feat(shougang): FileEncodingTransformer with classify + sequence logic"
```

---

## Task 7: 在 KnowledgeFilePipeline 注册 FileEncodingTransformer

**Files:**
- Modify: `src/backend/bisheng/knowledge/rag/knowledge_file_pipeline.py`

- [ ] **Step 1: 顶部 import**

打开 `src/backend/bisheng/knowledge/rag/knowledge_file_pipeline.py`,在 import 块(约 line 1–19)的末尾(`SplitterTransformer` 那行附近)加上:

```python
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
```

- [ ] **Step 2: 在 _init_common_transformers 中注册**

定位到 `_init_common_transformers` 方法(约 line 68)。它的开头是:

```python
def _init_common_transformers(self) -> List[BaseDocumentTransformer]:
    abstract_transformers = self._init_abstract_transformers()
    abstract_transformers.append(ExtraFileTransformer(...))
```

在 `abstract_transformers = self._init_abstract_transformers()` 这一行**之后**、`abstract_transformers.append(ExtraFileTransformer(...))` **之前**,插入:

```python
    # FileEncodingTransformer 紧跟 AbstractTransformer (in _init_abstract_transformers),
    # 利用 abstract 字段做 LLM 分类。shougang 关闭时内部会 skip,无副作用。
    abstract_transformers.append(FileEncodingTransformer(
        invoke_user_id=self.invoke_user_id,
        knowledge_file=self.db_file,
    ))
```

注:`self.invoke_user_id` 和 `self.db_file` 应该是 pipeline 类已有的属性。如果属性名不同(比如 `self.user_id`),按实际名称替换。

- [ ] **Step 3: 验证 pipeline 能正确实例化**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/python -c "
from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline
print('imports ok')
"
```
Expected: `imports ok` 不报错

- [ ] **Step 4: 提交**

```bash
git add src/backend/bisheng/knowledge/rag/knowledge_file_pipeline.py
git commit -m "feat(shougang): register FileEncodingTransformer in pipeline"
```

---

## Task 8: 添加 `FileEncodingUpdateReq` schema

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`(在 `FileRenameReq` 之后,约 line 86)

- [ ] **Step 1: 添加 schema**

打开 `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`,在 `FileRenameReq` 类定义之后(约 line 87),插入:

```python
class FileEncodingUpdateReq(BaseModel):
    encoding: str = Field(
        ..., min_length=1, max_length=64,
        description="New file encoding (free text, 1-64 chars)",
    )
```

- [ ] **Step 2: 提交**

```bash
git add src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py
git commit -m "feat(shougang): FileEncodingUpdateReq schema"
```

---

## Task 9: 添加 `update_file_encoding` 服务方法 + 端点(TDD 端点)

**Files:**
- Create: `src/backend/test/integration/test_update_file_encoding_endpoint.py`
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`(在 `rename_file` 之后,约 line 1956)
- Modify: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`(在 `rename_file` 端点之后,约 line 354)

- [ ] **Step 1: 写 failing 集成测试**

创建 `src/backend/test/integration/test_update_file_encoding_endpoint.py`:

```python
"""Integration tests for PUT /api/v1/knowledge/space/{sid}/files/{fid}/encoding."""
import pytest


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_update_file_encoding_success(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": "MY-CUSTOM-CODE-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    assert body["data"]["file_encoding"] == "MY-CUSTOM-CODE-001"


@pytest.mark.asyncio
async def test_update_file_encoding_rejects_empty(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_file_encoding_rejects_too_long(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": "X" * 65},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_file_encoding_denies_non_owner(authenticated_member_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_member_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": "ABC-123"},
    )
    # 期望权限被拒(具体状态码视项目错误处理 — 可能 403 或自定义业务码)
    assert resp.status_code in (403, 200)
    if resp.status_code == 200:
        body = resp.json()
        assert body["status_code"] != 200, "expected permission error in response body"


@pytest.mark.asyncio
async def test_update_file_encoding_404_for_unknown_file(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/999999999/encoding",
        json={"encoding": "ABC-123"},
    )
    assert resp.status_code in (404, 200)
    if resp.status_code == 200:
        body = resp.json()
        assert body["status_code"] != 200
```

注: `authenticated_owner_client`, `authenticated_member_client`, `sample_space_with_file` 是项目已有的 conftest fixtures(在 `src/backend/test/integration/conftest.py` 或类似文件中)。如果项目没有完全对应的 fixtures,实现这一步前需要先去 conftest 中确认 / 仿写。如果 fixture 名称略有差异,做相应调整。

- [ ] **Step 2: 运行测试,确认失败(端点未实现)**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/pytest test/integration/test_update_file_encoding_endpoint.py -v
```
Expected: 404 / fixture missing / endpoint not found

- [ ] **Step 3: 实现 service method**

打开 `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`,在 `rename_file` 方法定义之后(`return updated_file` 之后,约 line 1957),插入:

```python
    async def update_file_encoding(
        self, file_id: int, encoding: str,
    ) -> KnowledgeFile:
        """Update a file's file_encoding (shougang feature). Owner/admin only."""
        file_record = await self._get_file_for_action(file_id)
        # 权限: 复用 'rename_file' (该 action 仅 owner/admin 拥有,与编辑编码权限等级相符)
        await self._require_permission_id(
            'knowledge_file', file_id, 'rename_file',
            space_id=file_record.knowledge_id,
        )

        # pydantic min_length=1 已确保非空。strip 后再次确认空白也被拒。
        cleaned = encoding.strip()
        if not cleaned:
            raise ValueError("encoding cannot be empty after strip")

        file_record.file_encoding = cleaned
        file_record.updater_id = self.login_user.user_id
        file_record.updater_name = self.login_user.user_name
        return await KnowledgeFileDao.async_update(file_record)
```

确认 `KnowledgeFileDao` 已在文件顶部 import(在已有的 imports 中应该有)。

- [ ] **Step 4: 实现端点**

打开 `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`:

(a) 在顶部 import 中加入(找到现有的 `FileCreateReq, FileRenameReq` import 行,加上 `FileEncodingUpdateReq`):

```python
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    # ... existing imports
    FileCreateReq, FileRenameReq, FileEncodingUpdateReq,
    # ... rest
)
```

(b) 在 `rename_file` 端点之后(约 line 354,即 `delete_file` 端点之前),插入:

```python
@router.put('/{space_id}/files/{file_id}/encoding')
async def update_file_encoding(
        space_id: int,
        file_id: int,
        req: FileEncodingUpdateReq,
        svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.update_file_encoding(file_id, req.encoding)
    return resp_200(file_record)
```

- [ ] **Step 5: 运行测试,确认通过**

```bash
.venv/bin/pytest test/integration/test_update_file_encoding_endpoint.py -v
```
Expected: 全部 5 个测试 PASS(允许个别在 fixture 不匹配时 SKIP)

- [ ] **Step 6: 提交**

```bash
git add src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py \
        src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py \
        src/backend/test/integration/test_update_file_encoding_endpoint.py
git commit -m "feat(shougang): PUT /encoding endpoint + service method + tests"
```

---

## Task 10: 在 `bsConfig` 端点暴露 shougang 开关

**Files:**
- Modify: `src/backend/bisheng/workstation/api/endpoints/config.py`(`get_config` 函数,约 line 19–31)

- [ ] **Step 1: 在响应中注入 shougang 字段**

打开 `src/backend/bisheng/workstation/api/endpoints/config.py`,在 `get_config` 函数中(已有的 `ret['linsight_invitation_code'] = ...` 行之前或 `return resp_200(...)` 之前),插入:

```python
    shougang_conf = await bisheng_settings.aget_shougang_conf()
    if shougang_conf.enabled:
        ret['shougang'] = {'enabled': True, 'prefix': shougang_conf.prefix}
    else:
        ret['shougang'] = {'enabled': False}
```

- [ ] **Step 2: 验证响应结构**

启动后端服务(或用单测)验证 `/api/v1/workstation/config` 返回中包含 `shougang` 字段。

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
# 假设服务已起在 7860,且有有效 token
curl -s -H "Authorization: Bearer <token>" http://localhost:7860/api/v1/workstation/config | python -m json.tool | grep shougang
```
Expected: 看到 `"shougang": {"enabled": false}` 或 `{"enabled": true, "prefix": "GF"}`(取决于 DB 中是否配了)

- [ ] **Step 3: 提交**

```bash
git add src/backend/bisheng/workstation/api/endpoints/config.py
git commit -m "feat(shougang): expose shougang flag in /workstation/config"
```

---

## Task 11: 前端 i18n keys (3 个 locale 文件)

**Files:**
- Modify: `src/frontend/client/src/locales/zh-Hans/translation.json`
- Modify: `src/frontend/client/src/locales/en/translation.json`
- Modify: `src/frontend/client/src/locales/ja/translation.json`

- [ ] **Step 1: 加 zh-Hans keys**

打开 `src/frontend/client/src/locales/zh-Hans/translation.json`,定位到 `com_knowledge` 命名空间内的 `"edit_tags": "编辑标签",` 行,在它**之后**(同一对象内),插入:

```json
"file_encoding": "文件编码",
"file_encoding_edit_title": "编辑文件编码",
"file_encoding_placeholder": "请输入编码",
"file_encoding_required": "编码不能为空",
"file_encoding_max_length": "最多 64 个字符",
"file_encoding_generating": "生成中...",
"file_encoding_update_success": "编码更新成功",
"file_encoding_update_failed": "编码更新失败",
```

确认 JSON 语法仍合法(逗号位置正确)。

- [ ] **Step 2: 加 en keys**

打开 `src/frontend/client/src/locales/en/translation.json`,定位到 `com_knowledge.edit_tags` 之后,插入:

```json
"file_encoding": "File Encoding",
"file_encoding_edit_title": "Edit File Encoding",
"file_encoding_placeholder": "Enter encoding",
"file_encoding_required": "Encoding is required",
"file_encoding_max_length": "Max 64 characters",
"file_encoding_generating": "Generating...",
"file_encoding_update_success": "Encoding updated",
"file_encoding_update_failed": "Failed to update encoding",
```

- [ ] **Step 3: 加 ja keys**

打开 `src/frontend/client/src/locales/ja/translation.json`,定位到 `com_knowledge.edit_tags` 之后,插入:

```json
"file_encoding": "ファイルコード",
"file_encoding_edit_title": "ファイルコードを編集",
"file_encoding_placeholder": "コードを入力",
"file_encoding_required": "コードは必須です",
"file_encoding_max_length": "最大 64 文字",
"file_encoding_generating": "生成中...",
"file_encoding_update_success": "コードを更新しました",
"file_encoding_update_failed": "コードの更新に失敗しました",
```

- [ ] **Step 4: 验证 JSON 合法性**

```bash
cd /Users/shanghang/dataelem/bisheng/src/frontend/client
node -e "JSON.parse(require('fs').readFileSync('src/locales/zh-Hans/translation.json'))"
node -e "JSON.parse(require('fs').readFileSync('src/locales/en/translation.json'))"
node -e "JSON.parse(require('fs').readFileSync('src/locales/ja/translation.json'))"
```
Expected: 三条命令都无输出(JSON 合法)

- [ ] **Step 5: 提交**

```bash
git add src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json
git commit -m "feat(shougang): i18n keys for file encoding (zh/en/ja)"
```

---

## Task 12: 前端类型扩展 + API client + bsConfig 默认值

**Files:**
- Modify: `src/frontend/client/src/api/knowledge.ts`(`KnowledgeFile` interface,约 line 149–177;新增 `updateFileEncoding` 函数)
- Modify: `src/frontend/client/src/types/chat/config.ts`(`BsConfig` 类型,约 line 505–550)
- Modify: `src/frontend/client/src/hooks/queries/endpoints/queries.ts`(`useGetBsConfig`,约 line 45–79)

- [ ] **Step 1: 扩展 `KnowledgeFile` interface**

打开 `src/frontend/client/src/api/knowledge.ts`,在 `KnowledgeFile` interface 中(约 line 174 `approvalReason?: string;` 之后),插入:

```typescript
    fileEncoding?: string | null;        // mapped from file_encoding
```

- [ ] **Step 2: 添加 `updateFileEncoding` API function**

在 `src/frontend/client/src/api/knowledge.ts` 文件末尾(或与其他更新函数同区域)添加:

```typescript
import axios from "~/api/request";  // 确认顶部已 import,若已有可省略

/**
 * Update a file's encoding (shougang feature). Owner/admin only.
 */
export async function updateFileEncoding(
    spaceId: string,
    fileId: string,
    encoding: string,
): Promise<KnowledgeFile> {
    return await axios.put(
        `/api/v1/knowledge/space/${spaceId}/files/${fileId}/encoding`,
        { encoding },
    );
}
```

注: 确认 `axios` 已经从 `~/api/request` import。如果文件已经在顶部 import,跳过那一行。

- [ ] **Step 3: 扩展 `BsConfig` 类型**

打开 `src/frontend/client/src/types/chat/config.ts`,在 `BsConfig` 的最后一个属性后(`waiting_list_url: string` 之后),插入:

```typescript
  shougang?: { enabled: boolean; prefix?: string };
```

- [ ] **Step 4: 扩展 `useGetBsConfig` 默认值**

打开 `src/frontend/client/src/hooks/queries/endpoints/queries.ts`,在 `useGetBsConfig` 函数体内,在 `if (!data.fileUpload) data.fileUpload = ...` 这一行**之后**,加上:

```typescript
            if (!data.shougang) data.shougang = { enabled: false };
```

- [ ] **Step 5: 跑前端 type-check**

```bash
cd /Users/shanghang/dataelem/bisheng/src/frontend/client
npx tsc --noEmit
```
Expected: 无错误(可能有项目本身已存在的不相关 warning,但与本次改动无关)

- [ ] **Step 6: 提交**

```bash
git add src/frontend/client/src/api/knowledge.ts \
        src/frontend/client/src/types/chat/config.ts \
        src/frontend/client/src/hooks/queries/endpoints/queries.ts
git commit -m "feat(shougang): extend KnowledgeFile / BsConfig types + updateFileEncoding API"
```

---

## Task 13: 前端 EditEncodingModal 组件

**Files:**
- Create: `src/frontend/client/src/pages/knowledge/SpaceDetail/EditEncodingModal.tsx`

- [ ] **Step 1: 创建组件**

创建 `src/frontend/client/src/pages/knowledge/SpaceDetail/EditEncodingModal.tsx`:

```tsx
import { useEffect, useState } from "react";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { useLocalize } from "~/hooks";
import { KnowledgeFile } from "~/api/knowledge";

interface EditEncodingModalProps {
    file: KnowledgeFile | null;
    open: boolean;
    onClose: () => void;
    onSubmit: (newEncoding: string) => Promise<void>;
}

export function EditEncodingModal({ file, open, onClose, onSubmit }: EditEncodingModalProps) {
    const localize = useLocalize();
    const [value, setValue] = useState<string>("");
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (open) {
            setValue(file?.fileEncoding ?? "");
        }
    }, [open, file?.fileEncoding]);

    const trimmed = value.trim();
    const error =
        !trimmed
            ? localize("com_knowledge.file_encoding_required")
            : trimmed.length > 64
                ? localize("com_knowledge.file_encoding_max_length")
                : "";

    const handleSubmit = async () => {
        if (error || submitting) return;
        setSubmitting(true);
        try {
            await onSubmit(trimmed);
            onClose();
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>
                        {localize("com_knowledge.file_encoding_edit_title")}
                    </DialogTitle>
                </DialogHeader>
                <div className="space-y-2">
                    <Input
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        placeholder={localize("com_knowledge.file_encoding_placeholder")}
                        maxLength={64}
                        autoFocus
                    />
                    {error && (
                        <p className="text-sm text-destructive">{error}</p>
                    )}
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} disabled={submitting}>
                        {localize("com_ui.cancel")}
                    </Button>
                    <Button
                        disabled={!!error || submitting}
                        onClick={handleSubmit}
                    >
                        {localize("com_ui.save")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
```

注: 实际项目里 `Dialog`, `Button`, `Input` 的 import 路径可能不是 `~/components/ui/Dialog` 而是 `~/components` 或 `@/components/ui/Dialog`。打开 `EditTagsModal.tsx` 看看它的 import 风格,严格对齐(skill 已确认 `EditTagsModal.tsx` 是模板)。如果发现差异,把 import 路径改成与 `EditTagsModal.tsx` 一致的形式。

- [ ] **Step 2: 跑 type-check**

```bash
cd /Users/shanghang/dataelem/bisheng/src/frontend/client
npx tsc --noEmit
```
Expected: 无新错误

- [ ] **Step 3: 提交**

```bash
git add src/frontend/client/src/pages/knowledge/SpaceDetail/EditEncodingModal.tsx
git commit -m "feat(shougang): EditEncodingModal component"
```

---

## Task 14: 在 FileTable 加文件编码列

**Files:**
- Modify: `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`

这是改动最大的一个文件,分多步小心处理。

**编辑顺序说明**:Step 1–7 修改的是同一文件的不同位置,互相之间引用了变量(如 cell 渲染引用 `canEditEncoding`,而它定义在 hook 设置步)。**只要所有步骤都完成,文件最终状态正确即可**;先后顺序不影响 type-check / 运行结果。建议按写代码的自然心智流推进:imports → 类型/常量 → state hooks → JSX。

- [ ] **Step 1: 顶部 import**

打开 `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`,在 imports 区(约 line 1–35)末尾加入:

```typescript
import { EditEncodingModal } from "./EditEncodingModal";
import { updateFileEncoding } from "~/api/knowledge";
import { useGetBsConfig } from "~/hooks/queries/endpoints/queries";
import { useToastContext } from "~/Providers";
import { useQueryClient } from "@tanstack/react-query";
```

如果这些 import 已部分存在(`useToastContext` / `useGetBsConfig` 等),不重复 import。

- [ ] **Step 2: 在 `COLUMN_CONFIG` 中加列**

找到 `COLUMN_CONFIG` 定义(约 line 45),修改为:

```typescript
const COLUMN_CONFIG = {
    checkbox: { minWidth: 48, initialWidth: 48 },
    name: { minWidth: 140, initialWidth: 280 },
    fileType: { minWidth: 100, initialWidth: 120 },
    size: { minWidth: 80, initialWidth: 120 },
    tags: { minWidth: 140, initialWidth: 200 },
    fileEncoding: { minWidth: 140, initialWidth: 180 },
    updateTime: { minWidth: 140, initialWidth: 180 },
    status: { minWidth: 120, initialWidth: 160 },
} as const;
```

- [ ] **Step 3: 在 `FileTableHeader` 中渲染列头(条件渲染)**

定位到 `FileTableHeader` 组件,找到 tags 列头(约 line 429–437)和 updateTime 列头(约 line 439–449)之间。在两者之间插入:

```tsx
{shougangEnabled && (
    <TableHead
        className="relative bg-[rgb(251,251,251)] p-0 font-normal text-[#4e5969]"
        style={{
            width: columnWidths.fileEncoding,
            minWidth: columnWidths.fileEncoding,
            maxWidth: columnWidths.fileEncoding,
        }}
    >
        <div className="flex items-center gap-1.5 border-l pl-3">
            {localize("com_knowledge.file_encoding")}
        </div>
        <ResizeHandle columnKey="fileEncoding" onResizeStart={onResizeStart} />
    </TableHead>
)}
```

`shougangEnabled` 需要从 `FileTableHeader` 的 props 拿到 — 在 props interface 中加 `shougangEnabled: boolean`。

- [ ] **Step 4: 在 `FileRow`(或主表格 body 渲染循环)中加单元格**

找到 file row 渲染区域(应在 `FileTable` 主组件内的 `<TableBody>`),在 tags 单元格和 updateTime 单元格之间插入:

```tsx
{shougangEnabled && (
    <TableCell
        style={{
            width: columnWidths.fileEncoding,
            minWidth: columnWidths.fileEncoding,
            maxWidth: columnWidths.fileEncoding,
        }}
        className="border-l"
    >
        {file.status === FileStatus.PROCESSING && !file.fileEncoding ? (
            <span className="text-muted-foreground italic text-sm">
                {localize("com_knowledge.file_encoding_generating")}
            </span>
        ) : file.fileEncoding ? (
            <button
                type="button"
                onClick={() => canEditEncoding && handleOpenEditEncoding(file)}
                disabled={!canEditEncoding}
                className={cn(
                    "flex items-center gap-1 text-sm",
                    canEditEncoding && "hover:underline cursor-pointer",
                )}
                title={file.fileEncoding}
            >
                {canEditEncoding && (
                    <PencilLineIcon className="size-3 opacity-60 shrink-0" />
                )}
                <span className="truncate">{file.fileEncoding}</span>
            </button>
        ) : (
            <span className="text-muted-foreground">—</span>
        )}
    </TableCell>
)}
```

- [ ] **Step 5: 在 `FileTable` 主组件中接入 hooks 和状态**

在 `FileTable` 函数组件顶部(props 解构后),加入:

```typescript
    const { data: bsConfig } = useGetBsConfig();
    const shougangEnabled = bsConfig?.shougang?.enabled ?? false;
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const localize = useLocalize();  // 如果上面已有,跳过

    const [editingEncodingFile, setEditingEncodingFile] = useState<KnowledgeFile | null>(null);

    // 暂时所有用户都可编辑;实现 currentUserRole 后此处替换为 role === 'creator' || role === 'admin'
    // TODO: 接入 currentUserRole 判定 (Task 15)
    const canEditEncoding = isAdmin;  // 复用现有 isAdmin prop 作为占位

    const handleOpenEditEncoding = (file: KnowledgeFile) => {
        setEditingEncodingFile(file);
    };

    const handleSubmitEncoding = async (newEncoding: string) => {
        if (!editingEncodingFile) return;
        try {
            const updated = await updateFileEncoding(
                String(editingEncodingFile.spaceId),
                String(editingEncodingFile.id),
                newEncoding,
            );
            // 局部更新 react-query 缓存。如果项目里 useGetSpaceChildren 暴露 queryKey,
            // 用其工厂;否则 invalidate 整页(简单兜底)。
            await queryClient.invalidateQueries({ predicate: (q) =>
                q.queryKey.some((k) => typeof k === "string" && k.includes("spaceChildren")),
            });
            showToast?.({
                message: localize("com_knowledge.file_encoding_update_success"),
                severity: "success",
            });
        } catch (e) {
            showToast?.({
                message: localize("com_knowledge.file_encoding_update_failed"),
                severity: "error",
            });
            throw e;
        }
    };
```

- [ ] **Step 6: 在 `FileTable` JSX 末尾挂上弹窗**

在 `FileTable` 组件的 return JSX 末尾(在最外层 fragment 或 div 闭合前),加上:

```tsx
{shougangEnabled && (
    <EditEncodingModal
        file={editingEncodingFile}
        open={!!editingEncodingFile}
        onClose={() => setEditingEncodingFile(null)}
        onSubmit={handleSubmitEncoding}
    />
)}
```

- [ ] **Step 7: 把 `shougangEnabled`, `canEditEncoding`, `handleOpenEditEncoding` 透传到 `FileTableHeader` 和行渲染处**

修改 `FileTableHeaderProps`(若是独立接口):加上 `shougangEnabled: boolean`。在调用 `<FileTableHeader ...>` 处加上 `shougangEnabled={shougangEnabled}`。

行渲染如果是子组件 `FileRow`,同样在它的 props 里加 `shougangEnabled, canEditEncoding, onEditEncoding`,并由父组件传入。如果是内联渲染(在 `FileTable.map(...)` 里),变量直接闭包可见,无需传递。

- [ ] **Step 8: type-check**

```bash
cd /Users/shanghang/dataelem/bisheng/src/frontend/client
npx tsc --noEmit
```
Expected: 无新错误

- [ ] **Step 9: 启动 dev server 手动验证**

```bash
cd /Users/shanghang/dataelem/bisheng/src/frontend/client
pnpm dev
```

打开浏览器访问知识空间-文件列表页面,在浏览器 devtools console 中执行:

```js
// 模拟开启 shougang 配置
window.__bsConfig = { shougang: { enabled: true, prefix: 'GF' } };
// 触发列表刷新或硬刷新页面
```

更准确的验证方法是去 DB 写入 `shougang` 配置后正常加载页面。

**手动测试清单**:
- [ ] shougang 关闭时,「文件编码」列不显示
- [ ] shougang 开启时,「文件编码」列出现在「标签」和「更新时间」之间
- [ ] 文件状态为 PROCESSING 且 fileEncoding=null 时,显示「生成中...」
- [ ] fileEncoding 有值时,显示该值并带编辑图标(若 admin)
- [ ] 点击编辑图标弹出弹窗,显示当前编码
- [ ] 弹窗内输入空字符串,「保存」按钮禁用,显示错误「编码不能为空」
- [ ] 弹窗内输入 65 字符,「保存」按钮禁用,显示错误「最多 64 个字符」
- [ ] 输入合法值后点「保存」,toast 显示「编码更新成功」,列表对应行编码更新
- [ ] 切换语言到 en/ja,所有文案对应翻译

- [ ] **Step 10: 提交**

```bash
git add src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx
git commit -m "feat(shougang): file encoding column in FileTable + edit modal integration"
```

---

## Task 15: 接入 currentUserRole 判定权限(可选/补充)

**Files:**
- Modify: `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`(及其调用方)

`canEditEncoding` 当前用 `isAdmin` 占位。spec 决策是「仅空间 owner/admin」,需要拿到「当前用户在该空间的角色」。

- [ ] **Step 1: 调研复用入口**

打开 `src/frontend/client/src/pages/knowledge/SpaceDetail/` 目录(FileTable 的父级页面),找到调用 FileTable 的组件 — 该组件应该已经从 `/api/v1/knowledge/space/{id}/info` 拿到了 `currentUserRole`(spec 第 6.1 节备注)。

```bash
grep -rn "user_role\|userRole\|currentUserRole\|space.*info" \
  src/frontend/client/src/pages/knowledge/SpaceDetail/ \
  src/frontend/client/src/api/knowledge.ts | head -20
```

- [ ] **Step 2: 把 `currentUserRole` 透传到 FileTable**

(具体改动取决于 Step 1 的调研结果)在父组件中拿到 `userRole`,作为 prop 传入 `FileTable`,然后在 `FileTable` 内部:

```typescript
interface FileTableProps {
    // ... existing
    currentUserRole?: SpaceRole;  // 'creator' | 'admin' | 'member'
}

// 替换 Task 14 Step 5 中的占位:
const canEditEncoding = currentUserRole === SpaceRole.CREATOR
                     || currentUserRole === SpaceRole.ADMIN;
```

注: `SpaceRole` 已在 `~/api/knowledge.ts` 定义(参考勘查报告 F3)。

- [ ] **Step 3: type-check + 手动验证**

```bash
cd /Users/shanghang/dataelem/bisheng/src/frontend/client
npx tsc --noEmit
```

手动测试: 用普通成员用户登录该空间,确认编辑按钮不可点;用空间 owner/admin 登录,确认可点。

- [ ] **Step 4: 提交**

```bash
git add src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx \
        src/frontend/client/src/pages/knowledge/SpaceDetail/<父组件文件>.tsx
git commit -m "feat(shougang): gate encoding edit on space owner/admin role"
```

---

## Task 16: 端到端手动验证

- [ ] **Step 1: 启动后端 + 前端**

```bash
cd /Users/shanghang/dataelem/bisheng/src/backend
.venv/bin/uvicorn bisheng.main:app --reload --port 7860 &

cd /Users/shanghang/dataelem/bisheng/src/frontend/client
pnpm dev
```

- [ ] **Step 2: DB 中开启 shougang 配置**

通过平台管理页 `/api/v1/config/save`(或直接改 DB `config` 表的 `initdb_config` key)写入:

```yaml
shougang:
  prefix: GF
  deployment_label: "首钢集团知识门户"
  portal_admin_url: "/portal-admin/"
```

- [ ] **Step 3: 配置 chat_title_llm**

通过平台 `/api/v1/llm/workbench` 端点,确认 `chat_title_llm` 已配置(应该已经配过,daily-chat 用)。

- [ ] **Step 4: 验证完整链路**

- [ ] 上传一个内容是「关于生产安全管理制度」的 PDF
- [ ] 上传后立即查看列表,该行编码列显示「生成中...」
- [ ] 等待 ~30 秒(LLM 解析 + 编码生成)
- [ ] 刷新列表,编码列显示形如 `GF-ZD-AQ-202604-00001`(实际类型/业务域可能不同,看 LLM 判断)
- [ ] 点击编辑,改成 `MY-CUSTOM-001`,保存,看到 toast 成功提示
- [ ] 上传第二个文件,编码序号应递增至 `00002`
- [ ] 关闭 shougang(prefix 改空字符串或删除整块),刷新前端,编码列消失
- [ ] 关闭后再上传文件,新文件无编码;之前的编码值保留

- [ ] **Step 5: 后端日志检查**

```bash
grep -E '\[shougang.encoding\]' src/backend/logs/*.log | tail -20
```

确认看到:
- INFO 级日志: `[shougang.encoding] file_id=X ym=YYYYMM seq=NNNNN type_business=XX-YY encoding=...`
- WARN 级 fallback 日志(如果命中了兜底)

- [ ] **Step 6: 数据库验证**

```sql
SELECT id, file_name, file_encoding, create_time
FROM knowledge_file
WHERE file_encoding IS NOT NULL
ORDER BY create_time DESC
LIMIT 10;
```

确认编码格式正确,序号递增。

---

## Task 17 (可选): 监控 / 验收

- [ ] 跑全套后端单测确认无回归: `cd src/backend && .venv/bin/pytest test/unit -v`
- [ ] 跑前端 type-check 确认无错: `cd src/frontend/client && npx tsc --noEmit`
- [ ] 跑前端构建确认无错: `cd src/frontend/client && pnpm build`
- [ ] PR 提交时把 spec 链接放到 PR 描述,关联 issue/需求

---

## 验收标准 (来自 spec)

- [x] shougang 配置存在且 prefix 非空 → 启用编码;否则关闭
- [x] 启用后所有上传文件自动生成 `GF-XX-YY-YYYYMM-NNNNN` 编码
- [x] LLM 失败 / 未配置 → 兜底 `ZD-SC`,占序列号
- [x] 文件 retry 时编码不变(仅 NULL 时新生成)
- [x] 重复上传(MD5 命中)→ 编码继承原文件
- [x] 序列号月度全局递增,按 create_time 计算,封顶 99999
- [x] 前端列条件渲染,生成中显示 loading,编辑权限限定 owner/admin
- [x] 编辑接口校验非空 + 长度 ≤ 64,不回收原序列号
- [x] i18n 三语同步
- [x] 历史文件不回填,显示「—」
