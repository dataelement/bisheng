from __future__ import annotations

from typing import Any, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.sensitive_word.domain.schemas import SensitiveWordBusinessType
from bisheng.sensitive_word.domain.services.exceptions import ContentSafetyViolation
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)


class ContentSafetyTransformer(BaseDocumentTransformer):
    def __init__(
        self,
        tenant_id: int,
        business_type: SensitiveWordBusinessType = SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
    ) -> None:
        self.tenant_id = tenant_id
        self.business_type = business_type

    def transform_documents(
        self,
        documents: Sequence[Document],
        **kwargs: Any,
    ) -> Sequence[Document]:
        text = '\n'.join(document.page_content or '' for document in documents)
        result = SensitiveWordPolicyService.check_text(
            tenant_id=self.tenant_id,
            business_type=self.business_type,
            text=text,
        )
        if result.enabled and result.hits:
            raise ContentSafetyViolation(result)
        return documents
