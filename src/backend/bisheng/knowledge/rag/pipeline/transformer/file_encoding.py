"""FileEncodingTransformer — generates a standardized file encoding for
shougang deployments. Inserted into the common transformer chain after
AbstractTransformer so the file's abstract is available for LLM classification.

Encoding format: PREFIX-DOCTYPE-DOMAIN-YYYYMM-NNNNN
Example: GF-ZD-SC-202604-00001
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger
from sqlalchemy import func, select

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.services.llm import LLMService

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

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        # Sync entry point. Pipeline.run calls this directly. Pipeline.arun's
        # default atransform_documents wraps us in a thread executor. In both
        # cases, no event loop is running on this thread — asyncio.run is safe.
        try:
            asyncio.run(self._do_work())
        except Exception as e:
            logger.warning(
                f"[shougang.encoding] file_id={getattr(self.knowledge_file, 'id', None)} "
                f"transformer_error: {e}"
            )
        return list(documents)

    async def _do_work(self) -> None:
        shougang_conf = await bisheng_settings.aget_shougang_conf()
        if not shougang_conf.enabled:
            return

        if self.knowledge_file.file_encoding:
            return

        try:
            type_business_code = await self._classify_with_llm()
            seq = await self._compute_seq()
            self.knowledge_file.file_encoding = self._compose_encoding(
                shougang_conf.prefix, type_business_code,
                self.knowledge_file.create_time, seq,
            )
            logger.info(
                f"[shougang.encoding] file_id={self.knowledge_file.id} "
                f"seq={seq:05d} type_business={type_business_code} "
                f"encoding={self.knowledge_file.file_encoding}"
            )
        except Exception as e:
            # Fallback: even if LLM fails entirely, attempt to write a fallback
            # encoding as long as the sequence number can be computed.
            try:
                seq = await self._compute_seq()
                self.knowledge_file.file_encoding = self._compose_encoding(
                    shougang_conf.prefix, FALLBACK,
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
                    KnowledgeFile.file_type == 1,
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
