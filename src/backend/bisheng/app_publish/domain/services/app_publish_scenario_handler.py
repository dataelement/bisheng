"""The ``app_publish_request`` approval scenario handler (design D7 / D9 / D10).

Duck-typed by design — the approval engine looks methods up by name and there
is no base class to inherit. The complete protocol is: ``validate`` /
``build_title`` / ``build_detail`` / ``build_business_link`` /
``resolve_approvers`` / ``on_approved`` / ``on_rejected`` / ``on_withdrawn`` /
``on_cancelled``. A missing method surfaces as an ``AttributeError`` deep inside
the engine at approval time, so ``test_publish_scenario_handler`` asserts all
nine exist.

Four facts that shaped this file:

* **``resolve_approvers`` must explicitly delegate.** The gate calls it and does
  nothing else — generic source types (``department_admin`` / ``tenant_admin`` /
  ``direct_user``) are only resolved because this method calls
  ``resolve_approvers_from_sources``. A handler that returns ``[]`` instead
  produces a symptom identical to "the operator configured no approvers"
  (design 坑 9).
* **The applicant filter lives here, at the exit, not in the shared resolver.**
  "The person who submitted must not approve their own release" is *this*
  scenario's rule; channel subscription and knowledge-space joins want the
  opposite. One resolver, two policies — the policy stays with the scenario.
* **Self-approval rides on the instance.** The engine has no channel for it:
  ``resolve_approvers`` returns ``list[int]`` and ``ApprovalGateResult`` has
  four fixed fields. So the flag is an attribute, which is only correct because
  ``publish_approval_service`` builds a fresh handler per request. Never make
  this a module-level singleton.
* **Everything the terminal callbacks need is in ``payload_snapshot``.** The
  outbox hands them ``(instance_id, payload_snapshot)`` and nothing else — a
  handler that had to re-derive ``app_id`` from the instance would be querying
  the approval module's tables from F055.

Callback boundary (design K3 / 坑 10), stated once because getting it wrong is
invisible in tests that only check the happy path: the outbox decides success
purely by "did this raise". "待上线 (capacity / start failure)" is a *product
terminal state* with an application state, a notification and a publish-face
rendering — it must return normally. Only a broken system raises. The rule is
"will the application get better on its own — will it, return; won't it, raise".
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction

#: The scenario code, used by the preset, the seed, the runtime factory and the
#: client's early dispatch. One spelling, one place.
SCENARIO_CODE = "app_publish_request"

RELEASE_KIND_INITIAL = "initial"
RELEASE_KIND_ITERATION = "iteration"

#: Human labels for the release kind. Chinese single-language, exactly like the
#: three scenario names already shipped — the admin page and the approval card
#: render these verbatim, and translating one while the others stay Chinese
#: reads as a bug in every non-Chinese locale (design 坑 24).
_RELEASE_KIND_TEXT = {RELEASE_KIND_INITIAL: "首发", RELEASE_KIND_ITERATION: "迭代"}


class AppPublishScenarioHandler:
    """One publish request's view of the approval engine. Build one per request."""

    scenario_code = SCENARIO_CODE

    def __init__(self) -> None:
        #: Set by :meth:`resolve_approvers` when the applicant was kept as their
        #: own approver. Read by ``publish_approval_service`` right after the
        #: gate returns, to write the ``app.release.self_approval`` audit row
        #: AC-17 requires. See the module docstring for why it is an attribute.
        self.last_self_approval = False

    # ------------------------------------------------------------------
    # Card rendering
    # ------------------------------------------------------------------

    async def validate(self, req, login_user) -> None:
        """No extra submission-time validation: the pipeline already ran precheck and the scan."""
        return None

    async def build_title(self, req) -> str:
        payload = _payload(req)
        kind = _RELEASE_KIND_TEXT.get(str(payload.get("release_kind")), "")
        return f"{payload.get('app_name') or req.business_name} · {kind}发布审批"

    async def build_detail(self, req) -> dict[str, Any]:
        """The approval card's payload — design §4.2 ④, verbatim.

        Structured rather than flat key-value because the four regions AC-24
        asks for (what is being released / at what tier / with which
        capabilities / to whom it becomes visible) do not survive the generic
        two-column grid: arrays are joined with ", ", objects render as
        ``[object Object]`` and unmapped keys show their raw English name.

        ``app_name`` / ``release_kind_text`` / ``tier_name`` are repeated flat at
        the top on purpose. A front end that has never heard of this scenario
        falls back to the generic grid, and those three are what make it still
        legible (design 坑 7). ``scenario_code`` is what the client early
        dispatches on to reach the dedicated panel instead.
        """
        payload = _payload(req)
        release_kind = str(payload.get("release_kind") or RELEASE_KIND_INITIAL)
        tier = payload.get("tier") if isinstance(payload.get("tier"), dict) else {}
        return {
            "scenario_code": SCENARIO_CODE,
            # -- flat fallback trio (design 坑 7) --------------------------
            "app_name": payload.get("app_name") or req.business_name,
            "release_kind_text": _RELEASE_KIND_TEXT.get(release_kind, release_kind),
            "tier_name": str(tier.get("name") or tier.get("code") or ""),
            # -- structured body ------------------------------------------
            "app_id": str(payload.get("app_id") or req.business_resource_id),
            "app_slug": payload.get("app_slug"),
            "owner_user_id": payload.get("owner_user_id"),
            "owner_user_name": payload.get("owner_user_name"),
            "source": payload.get("source") or "cli",
            "release_kind": release_kind,
            "version_id": payload.get("version_id"),
            "version_no": payload.get("version_no"),
            "submitted_at": payload.get("submitted_at"),
            "tier": tier,
            "capabilities": list(payload.get("capabilities") or []),
            # Owned by F056; the slot is fixed now so the client panel does not
            # have to change shape when the visibility region lands.
            "visibility_snapshot": list(payload.get("visibility_snapshot") or []),
            # Structural evolution is a deferred wave — ``null`` means "not
            # evaluated", which is what the panel renders as "无结构变更".
            "schema_change": payload.get("schema_change"),
            "approver_note": payload.get("approver_note"),
        }

    async def build_business_link(self, req) -> dict[str, Any]:
        """Where an approver goes to see the application itself: the detail page's publish tab."""
        app_id = str(_payload(req).get("app_id") or req.business_resource_id)
        return {"app_id": app_id, "tab": "publish", "path": f"/build/apps/{app_id}?tab=publish"}

    # ------------------------------------------------------------------
    # Approver resolution (AC-12 / AC-14 / AC-17)
    # ------------------------------------------------------------------

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        """Resolve the node's approvers, then drop the applicant.

        Order is deliberate: resolve everybody first, filter second. Filtering
        inside the resolver would hide the one case where the applicant must be
        kept — they are the only candidate — behind an empty list that looks
        exactly like a misconfiguration.
        """
        from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources

        self.last_self_approval = False

        sources = node_config.get("sources") or []
        if sources:
            candidates = await resolve_approvers_from_sources(sources, req)
        else:
            # A node an operator rebuilt by hand may carry plain user ids.
            raw = node_config.get("approver_user_ids") or node_config.get("user_ids") or []
            candidates = [int(one) for one in raw]

        applicant = int(getattr(req, "applicant_user_id", 0) or 0)
        filtered = [user_id for user_id in candidates if user_id != applicant]
        if filtered or not candidates:
            return filtered

        # Everybody who resolved *is* the applicant. Filtering them out too
        # would deadlock a deployment with a single administrator — which is
        # what a single-tenant install is — so self-approval is allowed here
        # and audited by the caller (AC-17).
        self.last_self_approval = True
        logger.info(
            f"app_publish.self_approval applicant={applicant} business_key={getattr(req, 'business_key', None)}"
        )
        return [applicant]

    # ------------------------------------------------------------------
    # Terminal callbacks
    # ------------------------------------------------------------------

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict[str, Any]:
        """Approval passed: stage the version, then try to bring it online (design D9).

        Runs on a Celery worker through the approval outbox. See the module
        docstring for the return-vs-raise rule; the branches below are its only
        application.
        """
        from bisheng.app_publish.domain.services.publish_online_service import PublishOnlineService

        return await PublishOnlineService.bring_online(instance_id, payload_snapshot)

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        """Rejected: latch the version, fail the attempt, leave the application alone.

        The application state is untouched on purpose — a first release stays a
        draft, an iteration keeps running its current version. That falls out
        for free because a rejected release never wrote ``pending_version_id``.
        """
        from bisheng.app_publish.domain.services.publish_terminal_service import PublishTerminalService

        await PublishTerminalService.on_rejected(payload_snapshot, reason=reason)

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        """Withdrawn by the owner. Notification of the approvers is the engine's job, not ours."""
        from bisheng.app_publish.domain.services.publish_terminal_service import PublishTerminalService

        await PublishTerminalService.on_withdrawn(payload_snapshot, reason=reason)

    async def on_cancelled(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        """The application was deleted, so the in-flight request was cancelled.

        ``terminal_state`` stays NULL: deleting an application hides its whole
        version list, so there is nothing for a fifth terminal value to be read
        from (design D6).
        """
        from bisheng.app_publish.domain.services.publish_terminal_service import PublishTerminalService

        await PublishTerminalService.on_cancelled(payload_snapshot, reason=reason)


def _payload(req) -> dict[str, Any]:
    """``req.payload_snapshot`` as a dict, whatever the engine handed us.

    The gate passes an ``ApprovalGateRequest``; a second-node advance passes a
    ``SimpleNamespace`` it built from the stored instance. Both carry the
    attribute, neither guarantees the type.
    """
    payload = getattr(req, "payload_snapshot", None)
    return payload if isinstance(payload, dict) else {}


#: Audit actions this handler's callbacks are responsible for. Imported by the
#: terminal service; kept next to the handler so the mapping between "which
#: callback fired" and "which audit row appears" is readable in one place.
CALLBACK_AUDIT_ACTIONS = {
    "on_rejected": AppReleaseAuditAction.REJECTED,
    "on_withdrawn": AppReleaseAuditAction.WITHDRAWN,
    "on_cancelled": AppReleaseAuditAction.CANCELLED,
}
