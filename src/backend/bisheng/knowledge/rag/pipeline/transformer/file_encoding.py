"""FileEncodingTransformer generates a standardized file encoding for
shougang deployments.

Encoding format: COMPANY-DOCTYPE-DOMAIN-YYYYMMNNNNNNNN
Example: SGGF-RPT-PP-20260500000001
"""
from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger
from sqlalchemy import and_, func, or_, select

# Single dedicated async runner shared by ALL FileEncodingTransformer
# instances across all celery worker threads. Reasoning:
#   - bisheng_settings.aget_all_config() (and other async getters) cache
#     aiomysql / aioredis clients bound to the asyncio loop they were
#     first created on.
#   - The celery worker uses -P threads with -c >= 1, so multiple worker
#     threads call transform_documents concurrently. If each thread
#     creates its own loop, the cached connections end up bound to one
#     thread's loop and the others hit "Future attached to a different
#     loop" / "Event loop is closed".
#   - asyncio.run() closes the loop after each call, leaving cached
#     connections bound to a closed loop on the very next file.
# The fix: run all async work on ONE loop hosted on ONE dedicated daemon
# thread; threadpool worker threads submit coros via run_coroutine_threadsafe
# and block on the result. Cached connections live on that single loop
# for the lifetime of the process — no cross-loop or closed-loop errors.


class _AsyncRunner:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        if self._loop is not None and self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run, args=(loop,),
                daemon=True, name='shougang-encoding-async',
            )
            thread.start()
            self._loop = loop
            self._thread = thread

    @staticmethod
    def _run(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def submit(self, coro, timeout: float = 120.0):
        self._ensure_started()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)


_async_runner = _AsyncRunner()

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

CLASSIFY_PROMPT = """# 角色
你是一个企业文件编码分类助手。你的任务是根据给定的文件标题、摘要或正文内容,为文件生成标准化的文件编码。

# 任务目标
你需要从文件内容中识别出:
1. 一个"文档类型"
2. 一个"业务域"

然后按以下格式输出文件编码:
文档类型编码-业务域编码
例如: RPT-PP

# 编码规则
## 一、文档类型(必须且只能从以下枚举中选择一个)
- 政策制度 = POL
  - 适用于国家/行业法规、集团红头文件、管理政策、企业文化纲领等文件。
- 标准规范 = STD
  - 适用于国际标准、国家标准、行业标准、企业技术标准、产品标准、操作规程、安全规程、设计规范等文件。
- 流程方法 = PRO
  - 适用于管理流程、业务流程、工艺流程图、分析方法、实验方法、项目管理方法论等文件。
- 技术规程与诀窍 = SPC
  - 适用于最佳操作法、工艺优化参数、故障处理经验、设备调试心得、节能降耗小改小革等核心隐性知识文件。
- 报告 = RPT
  - 适用于科研报告、质量分析报告、事故分析报告、项目总结、对标报告、市场分析报告等文件。
- 案例库 = CAS
  - 适用于典型生产事故案例、设备故障案例、质量问题案例、工程项目案例、成功谈判/合作案例等文件。
- 设计资产 = DGN
  - 适用于工程设计图纸、工艺布局图、设备三维模型、PLC 程序、仿真模型等文件。
- 专利与知识产权 = PAT
  - 适用于专利文书、技术秘密认定文件、软件著作权、商标等文件。
- 培训资源 = TRN
  - 适用于培训课程、课件、教学视频、操作仿真软件、入职学习地图、技能认证题库等文件。
- 行业情报 = NEW
  - 适用于竞争对手动态、新技术跟踪、市场趋势分析、原材料价格情报、政策解读等文件。

## 二、业务域(必须且只能从以下枚举中选择一个)
- 生产 = PP
  - 适用于涵盖从原料处理到成品产出的全流程核心生产运营活动,包括烧结、炼铁、炼钢、连铸、热轧、冷轧等各工序的工艺技术、生产组织、调度操作、产线平衡、效率提升以及生产直接相关内容。
- 质量 = QM
  - 适用于从原料到成品的全流程质量控制、检测技术、实验室管理、质量体系等内容。
- 设备 = PM
  - 适用于通用设备管理,以及机械、电气、仪表、液压、传动等所有设备专业内容。
- 能源 = EM
  - 适用于水、电、风、气(汽)等能源介质的生产、输送、调度与高效利用。
- 安全 = SA
  - 适用于安全生产、消防安全、危险源管控、安全设施、职业健康。
- 环保 = EN
  - 适用于三废(气、水、固)治理、超低排放、节能技术、碳排放管理。
- 投资 = IM
  - 适用于战略规划、固定资产投资、股权投资、技改项目立项、可行性研究及后评价。
- 研发 = RD
  - 适用于新技术、新工艺、新产品、新材料的探索、实验与开发过程。
- 采购 = MM
  - 适用于原燃料(矿石、煤、焦)、备品备件、工程及服务类的采购寻源、供应商管理与招标。
- 营销 = SD
  - 适用于市场调研与开发、产品销售、客户服务、渠道管理、价格策略及合同物流管理。
- 财务 = FI
  - 适用于成本、预算、核算、税务、资金管理。
- 人力 = HR
  - 适用于招聘、培训、绩效、薪酬、劳动关系。
- 信息 = IT
  - 适用于软件、硬件、网络、数据中心、工业互联网、大数据、人工智能应用。
- 管理 = AD
  - 适用于战略、法务、审计、企管、行政、党群、宣传等通用管理知识。

# 判定原则
## 1. 总体要求
- 必须先判断"文档类型",再判断"业务域"。
- 只能使用上述枚举值,不允许输出未定义的类型、业务域或编码。
- 不允许根据个人理解自造缩写。

## 2. 输出要求
- 只输出最终编码
- 不要输出解释
- 不要输出多余文字
- 输出格式必须严格为: 文档类型编码-业务域编码, 例如: RPT-PP"""

VALID_PATTERN_TEXT = (
    r'^(POL|STD|PRO|SPC|RPT|CAS|DGN|PAT|TRN|NEW)-'
    r'(PP|QM|PM|EM|SA|EN|IM|RD|MM|SD|FI|HR|IT|AD)$'
)
VALID_PATTERN = re.compile(VALID_PATTERN_TEXT)
DEFAULT_COMPANY_CODE = "SGGF"
FALLBACK = "STD-PP"
SEQ_CAP = 99999999
DEFAULT_USER_CONTENT_TEMPLATE = "标题: {file_name}\n摘要: {abstract}"


@dataclass(frozen=True)
class FileEncodingRuntimeConfig:
    classify_prompt: str
    user_content_template: str
    valid_pattern: re.Pattern
    fallback_code: str
    seq_cap: int


class FileEncodingTransformer(BaseDocumentTransformer):
    """Generate file_encoding using LLM classification + monthly sequence.

    Skips when knowledge_file already has an encoding (idempotent for retries).
    """

    def __init__(self, invoke_user_id: int, knowledge_file: KnowledgeFile) -> None:
        self.invoke_user_id = invoke_user_id
        self.knowledge_file = knowledge_file

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        # Sync entry point. Pipeline.run calls this directly. Pipeline.arun's
        # default atransform_documents wraps us in a thread executor. We
        # delegate the actual async work to a single shared runner loop so
        # cached aiomysql/aioredis clients (in bisheng_settings) live on a
        # stable loop across all worker threads — see module top.
        try:
            _async_runner.submit(self._do_work())
        except Exception as e:
            logger.warning(
                f"[shougang.encoding] file_id={getattr(self.knowledge_file, 'id', None)} "
                f"transformer_error: {e}"
            )
        return list(documents)

    async def _do_work(self) -> None:
        shougang_conf = await bisheng_settings.aget_shougang_conf()
        encoding_config = self._resolve_encoding_config(shougang_conf)
        company_code = self._resolve_company_code(shougang_conf)

        if self.knowledge_file.file_encoding:
            return

        try:
            type_business_code = await self._classify_with_llm(encoding_config)
            seq = await self._compute_seq(encoding_config.seq_cap)
            self.knowledge_file.file_encoding = self._compose_encoding(
                company_code, type_business_code,
                self.knowledge_file.create_time, seq,
            )
            logger.info(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"seq={seq:08d} type_business={type_business_code} "
                f"encoding={self.knowledge_file.file_encoding}"
            )
        except Exception as e:
            # Fallback: even if LLM fails entirely, attempt to write a fallback
            # encoding as long as the sequence number can be computed.
            try:
                seq = await self._compute_seq(encoding_config.seq_cap)
                self.knowledge_file.file_encoding = self._compose_encoding(
                    company_code, encoding_config.fallback_code,
                    self.knowledge_file.create_time, seq,
                )
                logger.warning(
                    f"[shougang.encoding] file_id={self.knowledge_file.id} "
                    f"fallback used: {e}"
                )
            except Exception as inner:
                logger.error(
                    f"[shougang.encoding] file_id={self.knowledge_file.id} "
                    f"abandoned: outer={e} inner={inner}"
                )

    async def _classify_with_llm(self, encoding_config: FileEncodingRuntimeConfig | None = None) -> str:
        encoding_config = encoding_config or self._resolve_encoding_config(None)
        try:
            from bisheng.llm.domain.services.llm import LLMService

            # F022 INV-T18: classify against the KnowledgeFile's owner tenant
            # so the workbench config row resolves to that tenant's row (or
            # Root via share fallback) rather than the worker's empty
            # ContextVar.
            tenant_id = getattr(self.knowledge_file, 'tenant_id', None)
            llm_conf = await LLMService.get_workbench_llm(tenant_id=tenant_id)
            if (not llm_conf
                    or not llm_conf.chat_title_llm
                    or not llm_conf.chat_title_llm.id):
                logger.warning(
                    f"[shougang.encoding] file_id={self.knowledge_file.id} "
                    f"fallback: chat_title_llm_unset"
                )
                return encoding_config.fallback_code

            llm = await LLMService.get_bisheng_llm(
                model_id=llm_conf.chat_title_llm.id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                app_name='shougang_file_encoding',
                app_type=ApplicationTypeEnum.DAILY_CHAT,
                user_id=self.invoke_user_id,
            )

            response = await llm.ainvoke(self._build_classify_messages(encoding_config))
            result = (response.content or "").strip()

            if encoding_config.valid_pattern.match(result):
                return result
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"fallback: invalid_format raw={result!r}"
            )
            return encoding_config.fallback_code
        except Exception as e:
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"fallback: llm_error {e}"
            )
            return encoding_config.fallback_code

    def _resolve_encoding_config(self, shougang_conf: Any) -> FileEncodingRuntimeConfig:
        raw_config = getattr(shougang_conf, 'file_encoding', None) if shougang_conf is not None else None
        classify_prompt = self._resolve_nonempty_str(
            raw_config, 'classify_prompt', CLASSIFY_PROMPT,
        )
        user_content_template = self._resolve_user_content_template(raw_config)
        valid_pattern = self._resolve_valid_pattern(raw_config)
        fallback_code = self._resolve_fallback_code(raw_config, valid_pattern)
        seq_cap = self._resolve_seq_cap(raw_config)
        return FileEncodingRuntimeConfig(
            classify_prompt=classify_prompt,
            user_content_template=user_content_template,
            valid_pattern=valid_pattern,
            fallback_code=fallback_code,
            seq_cap=seq_cap,
        )

    def _build_classify_messages(self, encoding_config: FileEncodingRuntimeConfig) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": encoding_config.classify_prompt},
            {"role": "user", "content": self._format_user_content(encoding_config.user_content_template)},
        ]

    def _format_user_content(self, template: str) -> str:
        file_name = self.knowledge_file.file_name or ''
        abstract = self.knowledge_file.abstract or ''
        try:
            return template.format(file_name=file_name, abstract=abstract)
        except Exception as e:
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"invalid user_content_template, fallback to default: {e}"
            )
            return DEFAULT_USER_CONTENT_TEMPLATE.format(file_name=file_name, abstract=abstract)

    def _resolve_user_content_template(self, raw_config: Any) -> str:
        template = self._resolve_nonempty_str(
            raw_config, 'user_content_template', DEFAULT_USER_CONTENT_TEMPLATE,
        )
        try:
            template.format(file_name='', abstract='')
            return template
        except Exception as e:
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"invalid user_content_template config, fallback to default: {e}"
            )
            return DEFAULT_USER_CONTENT_TEMPLATE

    def _resolve_valid_pattern(self, raw_config: Any) -> re.Pattern:
        pattern_text = self._get_config_value(raw_config, 'valid_pattern')
        if not isinstance(pattern_text, str) or not pattern_text.strip():
            return VALID_PATTERN
        try:
            return re.compile(pattern_text.strip())
        except re.error as e:
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"invalid valid_pattern config, fallback to default: {e}"
            )
            return VALID_PATTERN

    def _resolve_fallback_code(self, raw_config: Any, valid_pattern: re.Pattern) -> str:
        fallback_code = self._get_config_value(raw_config, 'fallback_code')
        if isinstance(fallback_code, str) and fallback_code.strip():
            fallback_code = fallback_code.strip()
            if valid_pattern.match(fallback_code):
                return fallback_code
            logger.warning(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"invalid fallback_code config, fallback to default: {fallback_code!r}"
            )
        return FALLBACK

    def _resolve_seq_cap(self, raw_config: Any) -> int:
        seq_cap = self._get_config_value(raw_config, 'seq_cap')
        try:
            seq_cap = int(seq_cap)
        except (TypeError, ValueError):
            return SEQ_CAP
        if seq_cap > 0:
            return seq_cap
        logger.warning(
            f"[shougang.encoding] file_id={self.knowledge_file.id} "
            f"invalid seq_cap config, fallback to default: {seq_cap!r}"
        )
        return SEQ_CAP

    @classmethod
    def _resolve_nonempty_str(cls, raw_config: Any, key: str, default: str) -> str:
        value = cls._get_config_value(raw_config, key)
        if isinstance(value, str) and value.strip():
            return value
        return default

    @staticmethod
    def _get_config_value(raw_config: Any, key: str) -> Any:
        if raw_config is None:
            return None
        if isinstance(raw_config, dict):
            return raw_config.get(key)
        return getattr(raw_config, key, None)

    def _month_window(self) -> tuple[datetime, datetime]:
        ct = self.knowledge_file.create_time
        start = ct.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end

    async def _compute_seq(self, seq_cap: int = SEQ_CAP) -> int:
        start, end = self._month_window()
        async with get_async_db_session() as session:
            count = await session.scalar(
                select(func.count()).select_from(KnowledgeFile).where(
                    KnowledgeFile.create_time >= start,
                    KnowledgeFile.create_time < end,
                    KnowledgeFile.knowledge_id == self.knowledge_file.knowledge_id,
                    KnowledgeFile.file_type == 1,
                    or_(
                        KnowledgeFile.create_time < self.knowledge_file.create_time,
                        and_(
                            KnowledgeFile.create_time == self.knowledge_file.create_time,
                            KnowledgeFile.id <= self.knowledge_file.id,
                        ),
                    ),
                )
            )
        return self._cap_seq(count or 0, seq_cap=seq_cap)

    @staticmethod
    def _cap_seq(count: int, seq_cap: int = SEQ_CAP) -> int:
        if count < 1:
            return 1
        if count > seq_cap:
            return seq_cap
        return count

    @staticmethod
    def _resolve_company_code(shougang_conf: Any) -> str:
        prefix = getattr(shougang_conf, 'prefix', None)
        if isinstance(prefix, str) and prefix.strip():
            return prefix.strip()
        return DEFAULT_COMPANY_CODE

    @staticmethod
    def _compose_encoding(prefix: str, type_business: str,
                          create_time: datetime, seq: int) -> str:
        ym = create_time.strftime("%Y%m")
        return f"{prefix}-{type_business}-{ym}{seq:08d}"
