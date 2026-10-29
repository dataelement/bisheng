"""``bisheng-app.yaml`` — the authoritative schema (F055 design D3 / §4.2 ③).

This module is a **contract**, not an implementation detail: F053's CLI packs
against it, F054 reads ``runtime`` / ``port`` / ``tier`` / ``egress.domains``
out of the frozen copy, and release-contract table 1 assigns it to F055. Adding
or renaming a field here changes what every already-shipped CLI may write.

Design decisions worth not re-litigating:

* **pydantic v2 with ``extra='forbid'``**, not jsonschema and not hand-written
  checks. Zero new dependencies, and ``ValidationError.errors()`` hands over
  ``{loc, msg, type}`` triples that map straight onto AC-11's machine-readable
  half. Forbidding unknown keys is what turns ``runtimee:`` from a silently
  ignored line into "unknown field runtimee, did you mean runtime".
* **``runtime`` is a plain ``str`` here, validated against
  :data:`SUPPORTED_RUNTIMES` one layer up.** As an ``Enum`` field a bad value
  would come out of pydantic as a generic 16221 "manifest invalid"; the CLI's
  remedy for an unsupported runtime is completely different ("pick one of the
  runtimes this deployment ships"), so it gets its own code, 16222.
* **``manifest_version`` is the forward-compatibility gate.** The compatible
  direction (platform adds an optional field, an old CLI omits it) needs no
  gate. The other direction — a newer CLI writing keys this platform does not
  know — would otherwise surface as "unknown field", which tells the developer
  to delete the field rather than to upgrade the platform.
* **``tier`` is not resolved here.** The schema only sees a string; whether it
  exists and is still selectable is a DB question owned by
  ``ResourceTierService.resolve_tier`` (one definition of
  ``details.reason ∈ {not_found, disabled}``, which is what AC-46 / AC-47 are
  judged on).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Runtime templates this platform can build. A **local copy** of
#: runtime-manager's ``GET /v1/runtime/status.supported_runtimes``, on purpose:
#: the receive leg runs inside the HTTP request and must not issue an RPC (an
#: unreachable manager would turn ``deploy`` into a request hanging on a
#: timeout, design D4 / D1-C). The asynchronous leg re-checks against the
#: manager, so the cost of the copy is one queue round-trip on a wrong runtime.
#:
#: ⚠️ **F054 must change this constant in the same commit that adds a runtime
#: template** — otherwise a newly supported runtime is rejected 16222 in the
#: synchronous leg and never reaches the manager that would have accepted it.
#: Mirrors ``src/runtime-manager/runtime_manager/templates/`` (one entry per
#: template directory); an install that ships fewer templates is narrowed by
#: the asynchronous re-check, never widened.
SUPPORTED_RUNTIMES: tuple[str, ...] = ("python3.11", "node20", "static")

#: Highest ``manifest_version`` this platform understands.
SUPPORTED_MANIFEST_VERSION = 2

#: Icon constraints (design D12 / §4.2 ③). Oversized or odd-format icons are
#: skipped with a hint rather than failing the publish — an icon is metadata,
#: not a precondition.
MAX_ICON_BYTES = 1024 * 1024
ICON_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg")


class CapabilityModelRef(BaseModel):
    """A model the application declares it will call (capability bus wave)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, description="Display name as shown on the model management page")


class CapabilityKnowledgeBaseRef(BaseModel):
    """A knowledge base the application declares it will search (capability bus wave)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=128)
    id: str | None = Field(default=None, max_length=64)


class CapabilitySecretRef(BaseModel):
    """Only a name may be frozen into an application version."""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        from bisheng.app_publish.domain.secret_security import validate_name
        from bisheng.common.errcode.app_publish import AppSecretInvalidError

        try:
            return validate_name(value)
        except AppSecretInvalidError:
            raise ValueError("invalid_environment_name") from None


class CapabilityDeclaration(BaseModel):
    """Approved model, knowledge and name-only environment declarations."""

    model_config = ConfigDict(extra="forbid")

    models: list[CapabilityModelRef] = Field(default_factory=list)
    knowledge_bases: list[CapabilityKnowledgeBaseRef] = Field(default_factory=list)

    secrets: list[CapabilitySecretRef] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _unique_secret_names(self):
        names = [ref.name for ref in self.secrets]
        if len(names) != len(set(names)):
            raise ValueError("duplicate_environment_name")
        return self

    def is_empty(self) -> bool:
        return not self.models and not self.knowledge_bases and not self.secrets


class DatabaseColumn(BaseModel):
    """One declared column of an application table.

    ``type`` / ``nullable`` / ``default`` are the three attributes the
    structure-evolution precheck compares (AC-09): a column whose name survives
    but whose type, nullability or default changed is a *modification*, and a
    modification is breaking. ``extra="allow"`` keeps a developer's own
    annotations (``comment:`` / ``index:`` ...) out of the comparison and out
    of the refusal path — nothing outside those three attributes can fail a
    publish.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=64)
    type: str | None = Field(default=None, max_length=64)
    nullable: bool | None = None
    default: Any = None


class DatabaseTable(BaseModel):
    """One declared application table. Accepted but not created this round (D3).

    ``columns`` is what ``precheck_schema`` diffs across releases. A bare string
    entry (``columns: [id, name]``) is accepted as a name-only column so a
    manifest written before the attributes existed keeps validating.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=64)
    columns: list[DatabaseColumn] = Field(default_factory=list)

    @field_validator("columns", mode="before")
    @classmethod
    def _names_become_columns(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [{"name": item} if isinstance(item, str) else item for item in value]


class DatabaseDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tables: list[DatabaseTable] = Field(default_factory=list)


class EgressDeclaration(BaseModel):
    """Outbound allow-list. Format-checked only this round (F054 D12 owns enforcement)."""

    model_config = ConfigDict(extra="forbid")

    domains: list[str] = Field(default_factory=list)


class DependencyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lock: str | None = None
    offline_artifacts: list[str] = Field(default_factory=list)
    install_inputs: list[str] = Field(default_factory=list)

    @field_validator("lock")
    @classmethod
    def relative_lock(cls, value):
        if value is not None:
            from pathlib import PurePosixPath

            if (
                not value
                or "\\" in value
                or PurePosixPath(value).is_absolute()
                or any(part in {"", ".", ".."} for part in value.split("/"))
            ):
                raise ValueError("lock must be a safe package-relative path")
        return value


class StartupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: list[str] | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("command")
    @classmethod
    def valid_argv(cls, value):
        if value is not None and any(not arg or "\x00" in arg or len(arg) > 4096 for arg in value):
            raise ValueError("invalid startup command")
        return value


class BundleDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["bundle"] = "bundle"
    profile: str | None = None
    dependencies: DependencyInput = Field(default_factory=DependencyInput)
    startup: StartupInput = Field(default_factory=StartupInput)


class ImageDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["image"]
    image: str = Field(pattern=r"^(?:[A-Za-z0-9._/:-]+@)?sha256:[0-9a-f]{64}$")
    startup: StartupInput = Field(default_factory=StartupInput)


class SourceImageDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["source-image"]
    startup: StartupInput = Field(default_factory=StartupInput)


DeliveryInput = Annotated[BundleDelivery | ImageDelivery | SourceImageDelivery, Field(discriminator="mode")]


class AppManifest(BaseModel):
    """The parsed ``bisheng-app.yaml``. Unknown keys are an error, not a warning."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    manifest_version: int = Field(default=1, ge=1)
    delivery: DeliveryInput | None = None
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=256, description="Package-relative path to the icon file")
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)
    runtime: str = Field(min_length=1, max_length=32)
    port: int = Field(ge=1, le=65535)
    tier: str | None = Field(default=None, max_length=32, description="Tier code; None means 轻量 (AC-46)")
    capabilities: CapabilityDeclaration = Field(default_factory=CapabilityDeclaration)
    database: DatabaseDeclaration = Field(default_factory=DatabaseDeclaration)
    egress: EgressDeclaration = Field(default_factory=EgressDeclaration)

    @model_validator(mode="before")
    @classmethod
    def versioned_delivery(cls, document):
        if not isinstance(document, dict):
            return document
        document = dict(document)
        version = document.get("manifest_version", 1)
        if version == 1:
            if "delivery" in document:
                raise ValueError("delivery requires manifest_version 2")
        elif version == 2:
            delivery = document.get("delivery")
            if delivery is None:
                document["delivery"] = {"mode": "bundle"}
            elif isinstance(delivery, dict):
                document["delivery"] = {"mode": "bundle", **delivery}
        else:
            raise ValueError("unsupported manifest_version")
        return document

    @property
    def delivery_mode(self) -> str:
        return self.delivery.mode if self.delivery is not None else "source-image"

    def model_dump(self, **kwargs):
        result = super().model_dump(**kwargs)
        if self.manifest_version == 1:
            result.pop("delivery", None)
        return result


def egress_domains_of(manifest: dict[str, Any] | None) -> list[str]:
    """``egress.domains`` out of a **stored** manifest dict (F054 AC-16).

    Lives beside the schema because the key path is the schema's, and is
    defensive because the caller's input is not: ``app_version.manifest`` is a
    JSON column written by whichever version of the publish pipeline was
    running at the time, so any level of it can be the wrong shape.

    An unreadable declaration yields **nothing** rather than a guess. The
    manager denies by default, so the failure mode of being wrong here is "this
    application cannot reach its API" — visible, reported by the application
    itself, fixed by republishing — and never "this application can reach
    anything".
    """
    egress = manifest.get("egress") if isinstance(manifest, dict) else None
    domains = egress.get("domains") if isinstance(egress, dict) else None
    if not isinstance(domains, list):
        return []
    return [item.strip() for item in domains if isinstance(item, str) and item.strip()]
