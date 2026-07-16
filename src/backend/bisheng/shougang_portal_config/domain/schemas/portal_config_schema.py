import re
import secrets
import string
from copy import deepcopy
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


def _strip(value: Any) -> str:
    return str(value or "").strip()


_DOCUMENT_TYPE_CHILD_CODE_RANDOM_ALPHABET = string.ascii_uppercase + string.digits
_DOCUMENT_TYPE_CHILD_CODE_RANDOM_LENGTH = 4
_BUSINESS_DOMAIN_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,16}$")


def _normalize_document_type_code(value: Any) -> str:
    return _strip(value).upper()


def _generate_document_type_child_code(parent_code: str, used_codes: set[str]) -> str:
    while True:
        suffix = "".join(
            secrets.choice(_DOCUMENT_TYPE_CHILD_CODE_RANDOM_ALPHABET)
            for _ in range(_DOCUMENT_TYPE_CHILD_CODE_RANDOM_LENGTH)
        )
        code = f"{parent_code}-{suffix}"
        if code not in used_codes:
            return code


def _validate_optional_http_url(value: Any) -> str:
    text = _strip(value)
    if not text:
        return ""
    if not text.lower().startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")
    return text.rstrip("/")


def _is_http_url(value: Any) -> bool:
    text = _strip(value)
    if any(ord(char) < 32 for char in text):
        return False
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


class PortalDomainConfig(BaseModel):
    name: str
    space_ids: list[int] = Field(default_factory=list)
    color: str
    bg: str
    icon: str
    background_image: str = ""
    enabled: bool = True
    code: str = ""

    @model_validator(mode="after")
    def normalize(self):
        self.name = _strip(self.name)
        self.code = _strip(self.code).upper()
        if not self.name:
            raise ValueError("domain name is required")
        return self


class PortalSectionConfig(BaseModel):
    title: str
    tag: str
    link: str
    icon: str
    color: str = "#2563eb"
    bg: str = "#eff6ff"
    enabled: bool = True


class PortalQATemplateCategoryConfig(BaseModel):
    id: str
    name: str
    enabled: bool = True

    @model_validator(mode="after")
    def normalize(self):
        self.id = _strip(self.id)
        self.name = _strip(self.name)
        if not self.id:
            raise ValueError("template category id is required")
        if not self.name:
            raise ValueError("template category name is required")
        return self


class PortalQATemplateConfig(BaseModel):
    id: str
    name: str
    desc: str = ""
    category_id: str
    prompt: str
    icon: str
    home_icon: str = ""
    color: str
    bg: str
    enabled: bool = True
    show_on_home: bool = False

    @model_validator(mode="after")
    def normalize(self):
        self.id = _strip(self.id)
        self.name = _strip(self.name)
        self.category_id = _strip(self.category_id)
        self.prompt = _strip(self.prompt)
        self.icon = _strip(self.icon)
        self.color = _strip(self.color)
        self.bg = _strip(self.bg)
        if not self.id:
            raise ValueError("template id is required")
        if not self.name:
            raise ValueError("template name is required")
        if not self.category_id:
            raise ValueError("template category is required")
        if not self.prompt:
            raise ValueError("template prompt is required")
        if not self.icon:
            raise ValueError("template icon is required")
        if not self.color:
            raise ValueError("template color is required")
        if not self.bg:
            raise ValueError("template background color is required")
        return self


class PortalQAConfig(BaseModel):
    welcome_message: str = ""
    hot_questions: list[str] = Field(default_factory=list)
    ai_search_system_prompt: str = ""
    qa_system_prompt: str = ""
    quick_mode_system_prompt: str = ""
    normal_mode_system_prompt: str = ""
    expert_mode_system_prompt: str = ""
    selected_model: str = ""
    general_model: str = ""
    reasoning_model: str = ""
    template_categories: list[PortalQATemplateCategoryConfig] = Field(default_factory=list)
    templates: list[PortalQATemplateConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_refs(self):
        if not self.general_model and self.selected_model:
            self.general_model = self.selected_model
        if not self.selected_model and self.general_model:
            self.selected_model = self.general_model
        category_ids = [item.id for item in self.template_categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("template category ids must be unique")
        template_ids = [item.id for item in self.templates]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("template ids must be unique")
        valid_category_ids = set(category_ids)
        if any(item.category_id not in valid_category_ids for item in self.templates):
            raise ValueError("template category must exist")
        return self


class PortalAgentCategoryConfig(BaseModel):
    id: str
    name: str
    enabled: bool = True

    @model_validator(mode="after")
    def normalize(self):
        self.id = _strip(self.id)
        self.name = _strip(self.name)
        if not self.id:
            raise ValueError("agent category id is required")
        if not self.name:
            raise ValueError("agent category name is required")
        return self


class PortalAgentItemConfig(BaseModel):
    id: str
    type: Literal["workflow", "url"] = "workflow"
    workflow_id: str = ""
    url: str = ""
    name: str
    desc: str = ""
    category_id: str
    tags: list[str] = Field(default_factory=list)
    icon: str
    icon_image_url: str = ""
    color: str
    bg: str
    enabled: bool = True

    @model_validator(mode="after")
    def normalize(self):
        self.id = _strip(self.id)
        self.workflow_id = _strip(self.workflow_id)
        self.url = _strip(self.url)
        self.name = _strip(self.name)
        self.category_id = _strip(self.category_id)
        self.tags = [_strip(tag) for tag in self.tags if _strip(tag)]
        self.icon = _strip(self.icon)
        self.icon_image_url = _strip(self.icon_image_url)
        self.color = _strip(self.color)
        self.bg = _strip(self.bg)
        if not self.id:
            raise ValueError("application id is required")
        if self.type == "workflow" and not self.workflow_id:
            raise ValueError("workflow application requires workflow_id")
        if self.type == "url" and not _is_http_url(self.url):
            raise ValueError("url application requires a valid http/https url")
        if not self.name:
            raise ValueError("application name is required")
        if not self.category_id:
            raise ValueError("application category is required")
        if not self.icon:
            raise ValueError("application icon is required")
        if self.icon_image_url and not self.icon_image_url.startswith("/uploads/app-icons/"):
            raise ValueError("application icon image url is invalid")
        if not self.color:
            raise ValueError("application color is required")
        if not self.bg:
            raise ValueError("application background color is required")
        return self


class PortalAgentConfig(BaseModel):
    categories: list[PortalAgentCategoryConfig] = Field(default_factory=list)
    applications: list[PortalAgentItemConfig] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_agents(cls, value: Any):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "applications" not in data and isinstance(data.get("agents"), list):
            data["applications"] = data["agents"]
        data.pop("agents", None)
        return data

    @model_validator(mode="after")
    def validate_refs(self):
        category_ids = [item.id for item in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("agent category ids must be unique")
        application_ids = [item.id for item in self.applications]
        if len(application_ids) != len(set(application_ids)):
            raise ValueError("application ids must be unique")
        workflow_ids = [item.workflow_id for item in self.applications if item.type == "workflow"]
        if len(workflow_ids) != len(set(workflow_ids)):
            raise ValueError("workflow application ids must be unique")
        valid_category_ids = set(category_ids)
        if any(item.category_id not in valid_category_ids for item in self.applications):
            raise ValueError("application category must exist")
        return self


class PortalSearchConfig(BaseModel):
    rerank_model_id: str = ""


class PortalDocumentTypeChildConfig(BaseModel):
    code: str = ""
    label: str = ""


class PortalDocumentTypeConfig(BaseModel):
    code: str = ""
    label: str = ""
    description_examples: str = ""
    children: list[PortalDocumentTypeChildConfig] = Field(default_factory=list)

    @field_validator("description_examples", mode="before")
    @classmethod
    def normalize_description_examples(cls, value):
        return _strip(value)

    @model_validator(mode="before")
    @classmethod
    def fill_missing_child_codes(cls, value):
        if not isinstance(value, dict):
            return value
        next_value = dict(value)
        parent_code = _normalize_document_type_code(next_value.get("code"))
        raw_children = next_value.get("children")
        if not isinstance(raw_children, list) or not parent_code:
            return next_value

        used_codes: set[str] = set()
        children = []
        for child in raw_children:
            if not isinstance(child, dict):
                children.append(child)
                continue
            next_child = dict(child)
            child_code = _normalize_document_type_code(next_child.get("code"))
            child_label = _strip(next_child.get("label"))
            if child_code:
                used_codes.add(child_code)
                next_child["code"] = child_code
            elif child_label:
                generated_code = _generate_document_type_child_code(parent_code, used_codes)
                used_codes.add(generated_code)
                next_child["code"] = generated_code
            children.append(next_child)
        next_value["children"] = children
        return next_value


class PortalRecommendationConfig(BaseModel):
    provider: str
    home_strategy: str
    detail_strategy: str
    home_total_count: int = Field(default=20, ge=1, le=50, strict=True)
    hot_half_life_days: int = Field(default=7, ge=1, le=90, strict=True)
    home_entry_source_weight: float = Field(default=0.3, ge=0, le=1, allow_inf_nan=False)
    stable_shuffle_score_gap: float = Field(default=5, ge=0, le=100, allow_inf_nan=False)
    stable_shuffle_cycle_days: int = Field(default=7, ge=1, le=30, strict=True)
    personalized_shadow_enabled: StrictBool = False
    personalized_rollout_percent: int = Field(default=0, ge=0, le=100, strict=True)


class PortalDepartmentBusinessDomainBinding(BaseModel):
    department_id: int = Field(gt=0, strict=True)
    business_domain_codes: list[str] = Field(min_length=1)

    @field_validator("business_domain_codes", mode="before")
    @classmethod
    def normalize_business_domain_codes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("business_domain_codes must be a list")
        normalized = sorted({_strip(code).upper() for code in value if _strip(code)})
        invalid = [code for code in normalized if not _BUSINESS_DOMAIN_CODE_PATTERN.fullmatch(code)]
        if invalid:
            raise ValueError("business domain code is invalid")
        return normalized


class PortalDisplayHomeConfig(BaseModel):
    page_size: int | None = None
    section_page_size: int = Field(default=6, ge=1, le=50, strict=True)
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
    url: str = ""
    enabled: bool = True


class PortalBannerSlide(BaseModel):
    id: int
    label: str = ""
    title: str
    desc: str = ""
    image_url: str
    link_url: str = ""
    enabled: bool = True


class PortalIntegrationsConfig(BaseModel):
    bisheng_admin_entry_url: str = ""
    bisheng_knowledge_entry_url: str = ""


class PortalSiteConfig(BaseModel):
    header_brand_name: str = "首钢股份知库"
    header_logo_url: str = "/site-logo-new.png"
    login_brand_name: str = "首钢股份知库"
    login_logo_url: str = "/shougang-stock-logo.png"
    browser_title: str = "首钢股份知库"
    favicon_url: str = "/site-favicon-horizontal-v2.png"
    domain_count_cache_ttl_seconds: int = 43200
    home_cache_ttl_seconds: int = Field(default=1800, ge=60)


class PortalConfig(BaseModel):
    domains: list[PortalDomainConfig] = Field(default_factory=list)
    sections: list[PortalSectionConfig] = Field(default_factory=list)
    document_types: list[PortalDocumentTypeConfig] = Field(default_factory=list)
    qa: PortalQAConfig
    agent_config: PortalAgentConfig = Field(default_factory=PortalAgentConfig)
    search: PortalSearchConfig = Field(default_factory=PortalSearchConfig)
    recommendation: PortalRecommendationConfig
    department_business_domain_bindings: list[PortalDepartmentBusinessDomainBinding] = Field(default_factory=list)
    display: PortalDisplayConfig
    banners: list[PortalBannerSlide] = Field(default_factory=list)
    integrations: PortalIntegrationsConfig = Field(default_factory=PortalIntegrationsConfig)
    site: PortalSiteConfig = Field(default_factory=PortalSiteConfig)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_applications(cls, value: Any):
        if not isinstance(value, dict):
            return value
        data = deepcopy(value)

        # Before personalized recommendations, home sections could be configured
        # above the new Top-N default of 20. Preserve those valid legacy configs
        # only when home_total_count was not explicitly supplied; explicit values
        # still go through the cross-field validation below.
        raw_recommendation = data.get("recommendation")
        raw_display = data.get("display")
        raw_home = raw_display.get("home") if isinstance(raw_display, dict) else None
        section_page_size = raw_home.get("section_page_size") if isinstance(raw_home, dict) else None
        if (
            isinstance(raw_recommendation, dict)
            and "home_total_count" not in raw_recommendation
            and isinstance(section_page_size, int)
            and not isinstance(section_page_size, bool)
        ):
            recommendation = dict(raw_recommendation)
            recommendation["home_total_count"] = max(20, section_page_size)
            data["recommendation"] = recommendation

        raw_agent_config = data.get("agent_config")
        agent_config = dict(raw_agent_config) if isinstance(raw_agent_config, dict) else {}
        raw_applications = agent_config.get("applications")
        if isinstance(raw_applications, list):
            applications = [dict(item) for item in raw_applications if isinstance(item, dict)]
        else:
            raw_agents = agent_config.get("agents")
            applications = (
                [dict(item) for item in raw_agents if isinstance(item, dict)] if isinstance(raw_agents, list) else []
            )
        for application in applications:
            application.setdefault("type", "workflow")
            application.setdefault("workflow_id", "")
            application.setdefault("url", "")
            application.setdefault("icon_image_url", "")

        raw_categories = agent_config.get("categories")
        categories = (
            [dict(item) for item in raw_categories if isinstance(item, dict)]
            if isinstance(raw_categories, list)
            else []
        )
        legacy_apps = data.get("apps")
        valid_legacy_apps = (
            [dict(item) for item in legacy_apps if isinstance(item, dict) and _is_http_url(item.get("url"))]
            if isinstance(legacy_apps, list)
            else []
        )
        if valid_legacy_apps and not any(_strip(category.get("id")) == "url-apps" for category in categories):
            categories.append({"id": "url-apps", "name": "URL 应用", "enabled": True})

        existing_ids = {_strip(item.get("id")) for item in applications}
        for legacy in valid_legacy_apps:
            base_id = f"url-app-{legacy.get('id')}"
            existing = next((item for item in applications if _strip(item.get("id")) == base_id), None)
            if existing is not None:
                if _strip(existing.get("type")) == "url" and _strip(existing.get("url")) == _strip(legacy.get("url")):
                    continue
                suffix = 2
                candidate = f"{base_id}-{suffix}"
                while candidate in existing_ids:
                    suffix += 1
                    candidate = f"{base_id}-{suffix}"
                application_id = candidate
            else:
                application_id = base_id
            existing_ids.add(application_id)
            applications.append(
                {
                    "id": application_id,
                    "type": "url",
                    "workflow_id": "",
                    "url": _strip(legacy.get("url")),
                    "name": _strip(legacy.get("name")),
                    "desc": _strip(legacy.get("desc")),
                    "category_id": "url-apps",
                    "tags": [],
                    "icon": _strip(legacy.get("icon")) or "Globe",
                    "icon_image_url": "",
                    "color": _strip(legacy.get("color")) or "#2563eb",
                    "bg": _strip(legacy.get("bg")) or "#eff6ff",
                    "enabled": bool(legacy.get("enabled", True)),
                }
            )

        agent_config["categories"] = categories
        agent_config["applications"] = applications
        agent_config.pop("agents", None)
        data["agent_config"] = agent_config
        data.pop("apps", None)
        return data

    @model_validator(mode="after")
    def validate_personalized_recommendation_config(self):
        if self.recommendation.home_total_count < self.display.home.section_page_size:
            raise ValueError("recommendation.home_total_count must be >= display.home.section_page_size")

        enabled_domain_codes = {
            domain.code
            for domain in self.domains
            if domain.enabled and domain.code and _BUSINESS_DOMAIN_CODE_PATTERN.fullmatch(domain.code)
        }
        normalized_bindings: list[PortalDepartmentBusinessDomainBinding] = []
        seen_department_ids: set[int] = set()
        for binding in self.department_business_domain_bindings:
            if binding.department_id in seen_department_ids:
                raise ValueError("department_id must be unique in department business domain bindings")
            unknown_codes = set(binding.business_domain_codes) - enabled_domain_codes
            if unknown_codes:
                raise ValueError("business domain binding references a missing or disabled domain")
            seen_department_ids.add(binding.department_id)
            normalized_bindings.append(binding)
        self.department_business_domain_bindings = sorted(
            normalized_bindings,
            key=lambda item: item.department_id,
        )
        return self


class PortalBishengRuntimeConfig(BaseModel):
    base_url: AnyHttpUrl
    asset_base_url: str = ""
    username: str = ""
    timeout_seconds: float = 30.0
    saved_password: str = ""
    last_auth_at: str = ""

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value

    @field_validator("asset_base_url", mode="before")
    @classmethod
    def normalize_asset_base_url(cls, value: Any) -> str:
        return _validate_optional_http_url(value)


class PortalUnifiedAuthRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    provider: str = "group"
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    token_param_style: str = "query"
    state_secret: str = ""
    state_ttl_seconds: int = 300
    http_timeout_seconds: float = 10.0
    login_sync_hmac_secret: str = ""
    login_sync_signature_header: str = "X-Signature"

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, value: Any) -> str:
        provider = _strip(value).lower() or "group"
        if provider not in {"group", "stock", "custom"}:
            raise ValueError("provider must be group, stock or custom")
        return provider

    @field_validator("token_param_style", mode="before")
    @classmethod
    def validate_token_param_style(cls, value: Any) -> str:
        style = _strip(value).lower() or "query"
        if style not in {"query", "form"}:
            raise ValueError("token_param_style must be query or form")
        return style

    @field_validator("redirect_uri", "authorize_url", "token_url", "userinfo_url", mode="before")
    @classmethod
    def validate_urls(cls, value: Any) -> str:
        text = _strip(value)
        if not text:
            return ""
        if not text.lower().startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return text

    @field_validator(
        "client_id",
        "client_secret",
        "state_secret",
        "login_sync_hmac_secret",
        "login_sync_signature_header",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return _strip(value)

    @field_validator("state_ttl_seconds")
    @classmethod
    def validate_state_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("state_ttl_seconds must be positive")
        return value

    @field_validator("http_timeout_seconds")
    @classmethod
    def validate_http_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("http_timeout_seconds must be positive")
        return value


class PortalBishengRuntimeConfigView(BaseModel):
    base_url: AnyHttpUrl
    asset_base_url: str = ""
    username: str = ""
    timeout_seconds: float = 30.0
    has_saved_password: bool = False
    last_auth_at: str = ""


class PortalUnifiedAuthRuntimeConfigView(BaseModel):
    enabled: bool = False
    provider: str = "group"
    client_id: str = ""
    redirect_uri: str = ""
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    token_param_style: str = "query"
    state_ttl_seconds: int = 300
    http_timeout_seconds: float = 10.0
    login_sync_signature_header: str = "X-Signature"
    has_client_secret: bool = False
    has_state_secret: bool = False
    has_login_sync_hmac_secret: bool = False


class ShougangPortalAdminConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    portal: PortalConfig
    bisheng: PortalBishengRuntimeConfig
    unified_auth: PortalUnifiedAuthRuntimeConfig = Field(default_factory=PortalUnifiedAuthRuntimeConfig)


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
            login_sync_signature_header=(config.unified_auth.login_sync_signature_header or "X-Signature"),
            has_client_secret=bool(config.unified_auth.client_secret),
            has_state_secret=bool(config.unified_auth.state_secret),
            has_login_sync_hmac_secret=bool(config.unified_auth.login_sync_hmac_secret),
        ),
    )
