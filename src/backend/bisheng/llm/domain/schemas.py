from typing import Any

from pydantic import BaseModel, Field, model_validator

from bisheng.api.v1.schemas import WSModel
from bisheng.llm.domain.models import LLMModelBase, LLMServerBase
from bisheng.utils.mask_data import JsonFieldMasker


class SystemModelConfigEnvelope(BaseModel):
    """Generic envelope for the 5 GET ``/api/v1/llm/{type}`` endpoints.

    Wraps the typed config DTOs (KnowledgeLLMConfig / AssistantLLMConfig
    / ...) with the fallback metadata needed by the frontend banner
    system. ``inherited_from_root=True`` means the caller has no own
    row and the value came from Root via ``share_default_to_children``;
    ``fallback_blocked=True`` means Root has a row but opted out, so
    the frontend should hint that Root has not enabled sharing.
    """

    data: Any = Field(default=None, description="The original typed config payload")
    inherited_from_root: bool = Field(
        default=False,
        description="True when the value was inherited from Root (own row absent)",
    )
    fallback_blocked: bool = Field(
        default=False,
        description="True when Root has a row but share is disabled at Root level",
    )


class LLMModelInfo(LLMModelBase):
    id: int | None = None


class LLMServerInfo(LLMServerBase):
    id: int | None = None
    models: list[LLMModelInfo] = Field(default_factory=list, description="Model List")
    # Set by the Service layer when a Root-owned server is surfaced to a
    # Child caller — drives the frontend readonly Badge + disabled edit.
    is_root_shared_readonly: bool = Field(
        default=False,
        description="True when the caller sees this server via Root→Child share",
    )
    # Filled by the Service layer for super-admin callers viewing Root-owned
    # servers, by reading the FGA ``shared_with`` tuple set. Drives the
    # ModelConfig "share with child tenants" toggle. Always False for child
    # callers (they consume ``is_root_shared_readonly`` instead — no leak).
    share_to_children: bool = Field(
        default=False,
        description="True when this Root-owned server is currently shared to children",
    )
    # Display name of the owning tenant. Hydrated by the Service layer for
    # Root-owned rows so the frontend "Root 共享 · 只读" badge can render
    # the actual Root tenant name (e.g. "默认租户") instead of a hard-coded
    # "Root". None on Child-owned rows — the badge is not shown for those.
    tenant_name: str | None = Field(
        default=None,
        description="Display name of the owning tenant, populated for Root rows",
    )

    # Sensitive Data Desensitization
    @model_validator(mode="after")
    def mask_sensitive_data(self):
        if not self.config:
            return self
        mask_maker = JsonFieldMasker()
        self.config = mask_maker.mask_json(self.config)
        return self


class WorkbenchModelConfig(BaseModel):
    """
    Inspiration Model Configuration
    """

    # Daily-chat selectable model list. Migrated from WorkstationConfig.models.
    models: list[WSModel] | None = Field(
        default=None,
        description="Daily-chat selectable model list",
    )
    # Linsight default execution model — single-select id chosen from ``models`` (F035).
    # Replaces the removed ``task_model`` + ``linsight_executor_mode``; deepagents owns
    # the execution mode now, and the model is per-task selectable (design §2.2.1).
    linsight_default_model_id: str | None = Field(
        default=None,
        description="Linsight default execution model id (single-select from models)",
    )
    # RetrieveembeddingModels
    embedding_model: WSModel | None = Field(default=None, description="embeddingModels")
    # Speech-to-text model
    asr_model: WSModel | None = Field(default=None, description="Speech-to-text model")
    tts_model: WSModel | None = Field(default=None, description="Text-to-speech model")
    chat_title_llm: WSModel | None = Field(default=None, description="Chat Title Generation Model")


class LLMModelCreateReq(BaseModel):
    id: int | None = Field(default=None, description="Model UniqueID, Need to pass when updating")
    name: str = Field(..., description="Model Display Name")
    description: str | None = Field(default="", description="Model Description")
    model_name: str = Field(..., description="Model Name")
    model_type: str = Field(..., description="model type")
    online: bool = Field(default=True, description="Online")
    config: dict | None = Field(default=None, description="model config")


class LLMServerCreateReq(BaseModel):
    id: int | None = Field(default=None, description="service providerID, Need to pass when updating")
    name: str = Field(..., description="Support service provider name")
    description: str | None = Field(default="", description="Service Provider Description")
    type: str = Field(..., description="Service Provider Type")
    limit_flag: bool | None = Field(default=False, description="Whether to turn on the daily call limit")
    limit: int | None = Field(default=0, description="Daily call limit")
    config: dict | None = Field(default=None, description="Service Provider Configuration")
    # Root-only switch. Default True so Root creates are group-shared
    # unless the super admin explicitly opts out; ignored when the
    # caller is writing under a non-Root tenant.
    share_to_children: bool = Field(
        default=True,
        description="Fan out this server to all Children via FGA shared_with tuples",
    )
    models: list[LLMModelCreateReq] | None = Field(
        default_factory=list, description="List of models under Service Provider"
    )


class KnowledgeLLMConfig(BaseModel):
    embedding_model_id: int | None = Field(None, description="Knowledge Base DefaultembeddingModel'sID")
    source_model_id: int | None = Field(None, description="the Knowledge Base Traceability Model'sID")
    extract_title_model_id: int | None = Field(
        None, description="Documentation Knowledge Base Extraction Header Model'sID"
    )
    qa_similar_model_id: int | None = Field(None, description="QAThe Knowledge Base Similarity Question Model'sID")
    abstract_enabled: bool = Field(default=True, description="Whether to generate file summaries after parsing")
    auto_tag_enabled: bool = Field(default=True, description="Whether to generate file tags after upload parsing")
    abstract_prompt: str | None = Field(None, description="Summary Prompt")
    auto_tag_prompt: str | None = Field(
        None, description="Auto-tag system prompt; falls back to the built-in default when empty"
    )


class AssistantLLMItem(BaseModel):
    model_id: int | None = Field(None, description="Model'sID")
    agent_executor_type: str | None = Field(default="ReAct", description="Execution modefunction call or ReAct")
    knowledge_max_content: int | None = Field(
        default=15000, description="Maximum number of strings for knowledge base retrieval"
    )
    knowledge_sort_index: bool | None = Field(
        default=False, description="Whether to reschedule after knowledge base retrieval"
    )
    streaming: bool | None = Field(default=True, description="Whether to turn on streaming")
    default: bool | None = Field(default=False, description="Is default model")


class AssistantLLMConfig(BaseModel):
    llm_list: list[AssistantLLMItem] | None = Field(default_factory=list, description="Assistant OptionalLLMVertical")
    auto_llm: AssistantLLMItem | None = Field(
        None, description="Assistant Portrait Automatic Optimization Model Configuration"
    )


class EvaluationLLMConfig(BaseModel):
    model_id: int | None = Field(None, description="The default model of the evaluation functionID")
