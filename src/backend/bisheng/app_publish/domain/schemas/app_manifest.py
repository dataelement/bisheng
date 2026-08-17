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
  remedy for an unsupported runtime is completely different ("this deployment
  ships python3.11 only"), so it gets its own code, 16222.
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

from pydantic import BaseModel, ConfigDict, Field

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
SUPPORTED_RUNTIMES: tuple[str, ...] = ("python3.11",)

#: Highest ``manifest_version`` this platform understands.
SUPPORTED_MANIFEST_VERSION = 1

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


class CapabilityDeclaration(BaseModel):
    """``capabilities:`` — non-empty is refused this round (16231, design D16)."""

    model_config = ConfigDict(extra="forbid")

    models: list[CapabilityModelRef] = Field(default_factory=list)
    knowledge_bases: list[CapabilityKnowledgeBaseRef] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.models and not self.knowledge_bases


class DatabaseTable(BaseModel):
    """One declared application table. Accepted but not created this round (D3)."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=64)


class DatabaseDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tables: list[DatabaseTable] = Field(default_factory=list)


class EgressDeclaration(BaseModel):
    """Outbound allow-list. Format-checked only this round (F054 D12 owns enforcement)."""

    model_config = ConfigDict(extra="forbid")

    domains: list[str] = Field(default_factory=list)


class AppManifest(BaseModel):
    """The parsed ``bisheng-app.yaml``. Unknown keys are an error, not a warning."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    manifest_version: int = Field(default=1, ge=1)
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
