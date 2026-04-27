from typing import Optional, List

from pydantic import Field, BaseModel, model_validator

from bisheng.llm.domain.models import LLMModelBase, LLMServerBase
from bisheng.utils.mask_data import JsonFieldMasker
from bisheng_langchain.linsight.const import TaskMode


class LLMModelInfo(LLMModelBase):
    id: Optional[int] = None


class LLMServerInfo(LLMServerBase):
    id: Optional[int] = None
    models: List[LLMModelInfo] = Field(default_factory=list, description='Model List')
    # Set by the Service layer when a Root-owned server is surfaced to a
    # Child caller — drives the frontend readonly Badge + disabled edit.
    is_root_shared_readonly: bool = Field(
        default=False,
        description='True when the caller sees this server via Root→Child share',
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
    tenant_name: Optional[str] = Field(
        default=None,
        description="Display name of the owning tenant, populated for Root rows",
    )

    # Sensitive Data Desensitization
    @model_validator(mode='after')
    def mask_sensitive_data(self):
        if not self.config:
            return self
        mask_maker = JsonFieldMasker()
        self.config = mask_maker.mask_json(self.config)
        return self


class WSModel(BaseModel):
    key: Optional[str] = None
    id: str
    name: Optional[str] = None
    displayName: Optional[str] = None


class WorkbenchModelConfig(BaseModel):
    """
    Inspiration Model Configuration
    """
    # Task execution model
    task_model: Optional[WSModel] = Field(default=None, description='Task execution model')
    # RetrieveembeddingModels
    embedding_model: Optional[WSModel] = Field(default=None, description='embeddingModels')
    # Inspiration Execution Mode
    linsight_executor_mode: Optional[TaskMode] = Field(default=None, description='Inspiration Execution Mode')
    # Speech-to-text model
    asr_model: Optional[WSModel] = Field(default=None, description='Speech-to-text model')
    tts_model: Optional[WSModel] = Field(default=None, description='Text-to-speech model')
    chat_title_llm: Optional[WSModel] = Field(default=None, description='Chat Title Generation Model')


class LLMModelCreateReq(BaseModel):
    id: Optional[int] = Field(default=None, description='Model UniqueID, Need to pass when updating')
    name: str = Field(..., description='Model Display Name')
    description: Optional[str] = Field(default='', description='Model Description')
    model_name: str = Field(..., description='Model Name')
    model_type: str = Field(..., description='model type')
    online: bool = Field(default=True, description='Online')
    config: Optional[dict] = Field(default=None, description='model config')


class LLMServerCreateReq(BaseModel):
    id: Optional[int] = Field(default=None, description='service providerID, Need to pass when updating')
    name: str = Field(..., description='Support service provider name')
    description: Optional[str] = Field(default='', description='Service Provider Description')
    type: str = Field(..., description='Service Provider Type')
    limit_flag: Optional[bool] = Field(default=False, description='Whether to turn on the daily call limit')
    limit: Optional[int] = Field(default=0, description='Daily call limit')
    config: Optional[dict] = Field(default=None, description='Service Provider Configuration')
    # Root-only switch. Default True so Root creates are group-shared
    # unless the super admin explicitly opts out; ignored when the
    # caller is writing under a non-Root tenant.
    share_to_children: bool = Field(
        default=True,
        description='Fan out this server to all Children via FGA shared_with tuples',
    )
    models: Optional[List[LLMModelCreateReq]] = Field(default_factory=list,
                                                      description='List of models under Service Provider')


class KnowledgeLLMConfig(BaseModel):
    embedding_model_id: Optional[int] = Field(None, description="Knowledge Base DefaultembeddingModel'sID")
    source_model_id: Optional[int] = Field(None, description="the Knowledge Base Traceability Model'sID")
    extract_title_model_id: Optional[int] = Field(None,
                                                  description="Documentation Knowledge Base Extraction Header Model'sID")
    qa_similar_model_id: Optional[int] = Field(None, description="QAThe Knowledge Base Similarity Question Model'sID")
    abstract_prompt: Optional[str] = Field(None, description='Summary Prompt')


class AssistantLLMItem(BaseModel):
    model_id: Optional[int] = Field(None, description="Model'sID")
    agent_executor_type: Optional[str] = Field(default='ReAct',
                                               description='Execution modefunction call or ReAct')
    knowledge_max_content: Optional[int] = Field(default=15000,
                                                 description='Maximum number of strings for knowledge base retrieval')
    knowledge_sort_index: Optional[bool] = Field(default=False,
                                                 description='Whether to reschedule after knowledge base retrieval')
    streaming: Optional[bool] = Field(default=True, description='Whether to turn on streaming')
    default: Optional[bool] = Field(default=False, description='Is default model')


class AssistantLLMConfig(BaseModel):
    llm_list: Optional[List[AssistantLLMItem]] = Field(default_factory=list,
                                                       description='Assistant OptionalLLMVertical')
    auto_llm: Optional[AssistantLLMItem] = Field(None,
                                                 description='Assistant Portrait Automatic Optimization Model Configuration')


class EvaluationLLMConfig(BaseModel):
    model_id: Optional[int] = Field(None, description='The default model of the evaluation functionID')
