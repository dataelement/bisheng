from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip(value: Any) -> str:
    return str(value or '').strip()


def _validate_optional_http_url(value: Any) -> str:
    text = _strip(value)
    if not text:
        return ''
    if not text.lower().startswith(('http://', 'https://')):
        raise ValueError('url must start with http:// or https://')
    return text.rstrip('/')


class PortalDomainConfig(BaseModel):
    name: str
    space_ids: list[int] = Field(default_factory=list)
    color: str
    bg: str
    icon: str
    background_image: str = ''
    enabled: bool = True
    code: str = ''

    @model_validator(mode='after')
    def normalize(self):
        self.name = _strip(self.name)
        self.code = _strip(self.code).upper()
        if not self.name:
            raise ValueError('domain name is required')
        return self


class PortalSectionConfig(BaseModel):
    title: str
    tag: str
    link: str
    icon: str
    color: str = '#2563eb'
    bg: str = '#eff6ff'
    enabled: bool = True


class PortalQATemplateCategoryConfig(BaseModel):
    id: str
    name: str
    enabled: bool = True

    @model_validator(mode='after')
    def normalize(self):
        self.id = _strip(self.id)
        self.name = _strip(self.name)
        if not self.id:
            raise ValueError('template category id is required')
        if not self.name:
            raise ValueError('template category name is required')
        return self


class PortalQATemplateConfig(BaseModel):
    id: str
    name: str
    desc: str = ''
    category_id: str
    prompt: str
    icon: str
    home_icon: str = ''
    color: str
    bg: str
    enabled: bool = True
    show_on_home: bool = False

    @model_validator(mode='after')
    def normalize(self):
        self.id = _strip(self.id)
        self.name = _strip(self.name)
        self.category_id = _strip(self.category_id)
        self.prompt = _strip(self.prompt)
        self.icon = _strip(self.icon)
        self.color = _strip(self.color)
        self.bg = _strip(self.bg)
        if not self.id:
            raise ValueError('template id is required')
        if not self.name:
            raise ValueError('template name is required')
        if not self.category_id:
            raise ValueError('template category is required')
        if not self.prompt:
            raise ValueError('template prompt is required')
        if not self.icon:
            raise ValueError('template icon is required')
        if not self.color:
            raise ValueError('template color is required')
        if not self.bg:
            raise ValueError('template background color is required')
        return self


class PortalQAConfig(BaseModel):
    welcome_message: str = ''
    hot_questions: list[str] = Field(default_factory=list)
    ai_search_system_prompt: str = ''
    qa_system_prompt: str = ''
    quick_mode_system_prompt: str = ''
    normal_mode_system_prompt: str = ''
    expert_mode_system_prompt: str = ''
    selected_model: str = ''
    general_model: str = ''
    reasoning_model: str = ''
    template_categories: list[PortalQATemplateCategoryConfig] = Field(default_factory=list)
    templates: list[PortalQATemplateConfig] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_refs(self):
        if not self.general_model and self.selected_model:
            self.general_model = self.selected_model
        if not self.selected_model and self.general_model:
            self.selected_model = self.general_model
        category_ids = [item.id for item in self.template_categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError('template category ids must be unique')
        template_ids = [item.id for item in self.templates]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError('template ids must be unique')
        valid_category_ids = set(category_ids)
        if any(item.category_id not in valid_category_ids for item in self.templates):
            raise ValueError('template category must exist')
        return self


class PortalAgentCategoryConfig(BaseModel):
    id: str
    name: str
    enabled: bool = True

    @model_validator(mode='after')
    def normalize(self):
        self.id = _strip(self.id)
        self.name = _strip(self.name)
        if not self.id:
            raise ValueError('agent category id is required')
        if not self.name:
            raise ValueError('agent category name is required')
        return self


class PortalAgentItemConfig(BaseModel):
    id: str
    workflow_id: str
    name: str
    desc: str = ''
    category_id: str
    tags: list[str] = Field(default_factory=list)
    icon: str
    color: str
    bg: str
    enabled: bool = True

    @model_validator(mode='after')
    def normalize(self):
        self.id = _strip(self.id)
        self.workflow_id = _strip(self.workflow_id)
        self.name = _strip(self.name)
        self.category_id = _strip(self.category_id)
        self.tags = [_strip(tag) for tag in self.tags if _strip(tag)]
        self.icon = _strip(self.icon)
        self.color = _strip(self.color)
        self.bg = _strip(self.bg)
        if not self.id:
            raise ValueError('agent id is required')
        if not self.workflow_id:
            raise ValueError('agent workflow_id is required')
        if not self.name:
            raise ValueError('agent name is required')
        if not self.category_id:
            raise ValueError('agent category is required')
        if not self.icon:
            raise ValueError('agent icon is required')
        if not self.color:
            raise ValueError('agent color is required')
        if not self.bg:
            raise ValueError('agent background color is required')
        return self


class PortalAgentConfig(BaseModel):
    categories: list[PortalAgentCategoryConfig] = Field(default_factory=list)
    agents: list[PortalAgentItemConfig] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_refs(self):
        category_ids = [item.id for item in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError('agent category ids must be unique')
        agent_ids = [item.id for item in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError('agent ids must be unique')
        workflow_ids = [item.workflow_id for item in self.agents]
        if len(workflow_ids) != len(set(workflow_ids)):
            raise ValueError('agent workflow_ids must be unique')
        valid_category_ids = set(category_ids)
        if any(item.category_id not in valid_category_ids for item in self.agents):
            raise ValueError('agent category must exist')
        return self


class PortalSearchConfig(BaseModel):
    rerank_model_id: str = ''


class PortalDocumentTypeConfig(BaseModel):
    code: str = ''
    label: str = ''


class PortalRecommendationConfig(BaseModel):
    provider: str
    home_strategy: str
    detail_strategy: str


class PortalDisplayHomeConfig(BaseModel):
    page_size: int | None = None
    section_page_size: int = 6
    hot_tags_count: int = 8
    qa_hot_count: int = 4
    domain_count: int = 6
    spaces_count: int = 6
    apps_count: int = 6


class PortalDisplayListConfig(BaseModel):
    page_size: int = 10
    visible_tag_count: int = 2


class PortalDisplaySearchConfig(BaseModel):
    page_size: int = 10
    visible_tag_count: int = 2


class PortalDisplayDetailConfig(BaseModel):
    related_files_count: int = 3
    visible_tag_count: int = 2


class PortalDisplayConfig(BaseModel):
    home: PortalDisplayHomeConfig = Field(default_factory=PortalDisplayHomeConfig)
    list: PortalDisplayListConfig = Field(default_factory=PortalDisplayListConfig)
    search: PortalDisplaySearchConfig = Field(default_factory=PortalDisplaySearchConfig)
    detail: PortalDisplayDetailConfig = Field(default_factory=PortalDisplayDetailConfig)


class PortalAppConfig(BaseModel):
    id: int
    name: str
    icon: str
    desc: str
    color: str
    bg: str
    url: str = ''
    enabled: bool = True


class PortalBannerSlide(BaseModel):
    id: int
    label: str = ''
    title: str
    desc: str = ''
    image_url: str
    link_url: str = ''
    enabled: bool = True


class PortalIntegrationsConfig(BaseModel):
    bisheng_admin_entry_url: str = ''
    bisheng_knowledge_entry_url: str = ''


class PortalSiteConfig(BaseModel):
    header_brand_name: str = '首钢股份知库'
    header_logo_url: str = '/site-logo-new.png'
    login_brand_name: str = '首钢股份知库'
    login_logo_url: str = '/shougang-stock-logo.png'
    browser_title: str = '首钢股份知库'
    favicon_url: str = '/site-favicon-horizontal-v2.png'
    domain_count_cache_ttl_seconds: int = 43200


class PortalConfig(BaseModel):
    domains: list[PortalDomainConfig] = Field(default_factory=list)
    sections: list[PortalSectionConfig] = Field(default_factory=list)
    document_types: list[PortalDocumentTypeConfig] = Field(default_factory=list)
    qa: PortalQAConfig
    agent_config: PortalAgentConfig = Field(default_factory=PortalAgentConfig)
    search: PortalSearchConfig = Field(default_factory=PortalSearchConfig)
    recommendation: PortalRecommendationConfig
    display: PortalDisplayConfig
    apps: list[PortalAppConfig] = Field(default_factory=list)
    banners: list[PortalBannerSlide] = Field(default_factory=list)
    integrations: PortalIntegrationsConfig = Field(default_factory=PortalIntegrationsConfig)
    site: PortalSiteConfig = Field(default_factory=PortalSiteConfig)


class PortalBishengRuntimeConfig(BaseModel):
    base_url: AnyHttpUrl
    asset_base_url: str = ''
    username: str = ''
    timeout_seconds: float = 30.0
    saved_password: str = ''
    last_auth_at: str = ''

    @field_validator('timeout_seconds')
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError('timeout_seconds must be positive')
        return value

    @field_validator('asset_base_url', mode='before')
    @classmethod
    def normalize_asset_base_url(cls, value: Any) -> str:
        return _validate_optional_http_url(value)


class PortalUnifiedAuthRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')

    enabled: bool = False
    provider: str = 'group'
    client_id: str = ''
    client_secret: str = ''
    redirect_uri: str = ''
    authorize_url: str = ''
    token_url: str = ''
    userinfo_url: str = ''
    token_param_style: str = 'query'
    state_secret: str = ''
    state_ttl_seconds: int = 300
    http_timeout_seconds: float = 10.0
    login_sync_hmac_secret: str = ''
    login_sync_signature_header: str = 'X-Signature'

    @field_validator('provider', mode='before')
    @classmethod
    def validate_provider(cls, value: Any) -> str:
        provider = _strip(value).lower() or 'group'
        if provider not in {'group', 'stock', 'custom'}:
            raise ValueError('provider must be group, stock or custom')
        return provider

    @field_validator('token_param_style', mode='before')
    @classmethod
    def validate_token_param_style(cls, value: Any) -> str:
        style = _strip(value).lower() or 'query'
        if style not in {'query', 'form'}:
            raise ValueError('token_param_style must be query or form')
        return style

    @field_validator('redirect_uri', 'authorize_url', 'token_url', 'userinfo_url', mode='before')
    @classmethod
    def validate_urls(cls, value: Any) -> str:
        text = _strip(value)
        if not text:
            return ''
        if not text.lower().startswith(('http://', 'https://')):
            raise ValueError('url must start with http:// or https://')
        return text

    @field_validator(
        'client_id',
        'client_secret',
        'state_secret',
        'login_sync_hmac_secret',
        'login_sync_signature_header',
        mode='before',
    )
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return _strip(value)

    @field_validator('state_ttl_seconds')
    @classmethod
    def validate_state_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('state_ttl_seconds must be positive')
        return value

    @field_validator('http_timeout_seconds')
    @classmethod
    def validate_http_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError('http_timeout_seconds must be positive')
        return value


class PortalBishengRuntimeConfigView(BaseModel):
    base_url: AnyHttpUrl
    asset_base_url: str = ''
    username: str = ''
    timeout_seconds: float = 30.0
    has_saved_password: bool = False
    last_auth_at: str = ''


class PortalUnifiedAuthRuntimeConfigView(BaseModel):
    enabled: bool = False
    provider: str = 'group'
    client_id: str = ''
    redirect_uri: str = ''
    authorize_url: str = ''
    token_url: str = ''
    userinfo_url: str = ''
    token_param_style: str = 'query'
    state_ttl_seconds: int = 300
    http_timeout_seconds: float = 10.0
    login_sync_signature_header: str = 'X-Signature'
    has_client_secret: bool = False
    has_state_secret: bool = False
    has_login_sync_hmac_secret: bool = False


class ShougangPortalAdminConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')

    version: int = 1
    portal: PortalConfig
    bisheng: PortalBishengRuntimeConfig
    unified_auth: PortalUnifiedAuthRuntimeConfig = Field(
        default_factory=PortalUnifiedAuthRuntimeConfig
    )


class ShougangPortalAdminConfigView(BaseModel):
    version: int = 1
    portal: PortalConfig
    bisheng: PortalBishengRuntimeConfigView
    unified_auth: PortalUnifiedAuthRuntimeConfigView


def redact_portal_admin_config(config: ShougangPortalAdminConfig) -> ShougangPortalAdminConfigView:
    return ShougangPortalAdminConfigView(
        version=config.version,
        portal=config.portal,
        bisheng=PortalBishengRuntimeConfigView(
            base_url=config.bisheng.base_url,
            asset_base_url=config.bisheng.asset_base_url,
            username=config.bisheng.username,
            timeout_seconds=config.bisheng.timeout_seconds,
            has_saved_password=bool(config.bisheng.saved_password),
            last_auth_at=config.bisheng.last_auth_at,
        ),
        unified_auth=PortalUnifiedAuthRuntimeConfigView(
            enabled=config.unified_auth.enabled,
            provider=config.unified_auth.provider,
            client_id=config.unified_auth.client_id,
            redirect_uri=config.unified_auth.redirect_uri,
            authorize_url=config.unified_auth.authorize_url,
            token_url=config.unified_auth.token_url,
            userinfo_url=config.unified_auth.userinfo_url,
            token_param_style=config.unified_auth.token_param_style,
            state_ttl_seconds=config.unified_auth.state_ttl_seconds,
            http_timeout_seconds=config.unified_auth.http_timeout_seconds,
            login_sync_signature_header=(
                config.unified_auth.login_sync_signature_header or 'X-Signature'
            ),
            has_client_secret=bool(config.unified_auth.client_secret),
            has_state_secret=bool(config.unified_auth.state_secret),
            has_login_sync_hmac_secret=bool(config.unified_auth.login_sync_hmac_secret),
        ),
    )
