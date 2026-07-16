from __future__ import annotations

import hashlib
import inspect
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from loguru import logger


@dataclass(frozen=True, slots=True)
class PortalRecommendationScoringConfig:
    stable_shuffle_score_gap: float = 5.0
    stable_shuffle_cycle_days: int = 7

    def validate(self) -> None:
        if self.stable_shuffle_score_gap < 0:
            raise ValueError("stable_shuffle_score_gap must be non-negative")
        if self.stable_shuffle_cycle_days < 1:
            raise ValueError("stable_shuffle_cycle_days must be at least 1")


@dataclass(frozen=True, slots=True)
class PortalRecommendationCandidate:
    space_id: int
    file_id: int
    domain_score: float = 0.0
    interest_score: float = 0.0
    hot_score: float = 0.0
    fresh_score: float = 0.0
    is_public: bool = False
    normal_acl: bool = True
    eligible: bool = True
    base_score: float = 0.0
    read_penalty: float = 0.0
    final_score: float = 0.0

    @property
    def key(self) -> tuple[int, int]:
        return self.space_id, self.file_id


class PortalRecommendationPermissionContextUnavailable(RuntimeError):
    """The request-level permission context cannot safely authorize more files."""


@dataclass(slots=True)
class PortalRecommendationAuthorizationState:
    started_at: float | None = None
    checks: int = 0
    decisions: dict[tuple[int, int], bool] | None = None
    permission_context: Any = None
    context_initialized: bool = False
    unavailable: bool = False

    def __post_init__(self) -> None:
        if self.decisions is None:
            self.decisions = {}


PermissionContextFactory = Callable[[], Awaitable[Any]]
PermissionBatchChecker = Callable[
    [Any, Sequence[PortalRecommendationCandidate]],
    Awaitable[dict[tuple[int, int], bool | Exception]],
]
DomainPoolPageLoader = Callable[
    [str, int, int],
    Awaitable[Sequence[PortalRecommendationCandidate]],
]
CandidatePredicate = Callable[[PortalRecommendationCandidate], bool]


class PortalRecommendationService:
    MAX_LIGHTWEIGHT_CANDIDATES = 10_000
    DOMAIN_WEIGHT = 0.30
    INTEREST_WEIGHT = 0.40
    HOT_WEIGHT = 0.15
    FRESH_WEIGHT = 0.15

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock

    @staticmethod
    def active_signal_flags(
        candidates: Sequence[PortalRecommendationCandidate],
    ) -> tuple[bool, bool]:
        return (
            any(candidate.domain_score > 0 for candidate in candidates),
            any(candidate.interest_score > 0 for candidate in candidates),
        )

    @classmethod
    async def load_unique_domain_pool_candidates(
        cls,
        domain_codes: Sequence[str],
        *,
        load_page: DomainPoolPageLoader,
        reserved_keys: Iterable[tuple[int, int]] = (),
        page_size: int = 200,
        accept_candidate: CandidatePredicate | None = None,
    ) -> dict[str, list[PortalRecommendationCandidate]]:
        """Fill the global budget without imposing a lossy per-domain quota."""
        codes = sorted({str(code).strip().upper() for code in domain_codes if str(code).strip()})
        result = {code: [] for code in codes}
        if not codes:
            return result
        safe_page_size = min(max(int(page_size), 1), cls.MAX_LIGHTWEIGHT_CANDIDATES)
        seen = set(reserved_keys)
        offsets = dict.fromkeys(codes, 0)
        active = set(codes)
        while active and len(seen) < cls.MAX_LIGHTWEIGHT_CANDIDATES:
            progressed = False
            for code in codes:
                if code not in active or len(seen) >= cls.MAX_LIGHTWEIGHT_CANDIDATES:
                    continue
                remaining = cls.MAX_LIGHTWEIGHT_CANDIDATES - len(seen)
                request_size = min(safe_page_size, remaining)
                page = list(await load_page(code, offsets[code], request_size))
                offsets[code] += len(page)
                if len(page) < request_size:
                    active.discard(code)
                if page:
                    progressed = True
                for candidate in page:
                    if accept_candidate is not None and not accept_candidate(candidate):
                        continue
                    if candidate.key in seen:
                        continue
                    seen.add(candidate.key)
                    result[code].append(candidate)
                    if len(seen) >= cls.MAX_LIGHTWEIGHT_CANDIDATES:
                        break
            if not progressed:
                break
        return result

    @classmethod
    def merge_ordered_candidates(
        cls,
        *sources: Sequence[PortalRecommendationCandidate],
        limit: int | None = None,
    ) -> list[PortalRecommendationCandidate]:
        result: list[PortalRecommendationCandidate] = []
        seen: set[tuple[int, int]] = set()
        safe_limit = min(
            max(int(limit or cls.MAX_LIGHTWEIGHT_CANDIDATES), 1),
            cls.MAX_LIGHTWEIGHT_CANDIDATES,
        )
        for source in sources:
            for candidate in source:
                if candidate.key in seen:
                    continue
                seen.add(candidate.key)
                result.append(candidate)
                if len(result) >= safe_limit:
                    return result
        return result

    @staticmethod
    def _clamp_feature(value: float) -> float:
        return min(max(float(value), 0.0), 100.0)

    @staticmethod
    def _read_penalty(read_at: datetime | None, now: datetime) -> float:
        if read_at is None:
            return 0.0
        if read_at.tzinfo is None:
            read_at = read_at.replace(tzinfo=timezone.utc)
        age_days = max((now - read_at).total_seconds(), 0) / 86400
        if age_days <= 7:
            return -80.0
        if age_days <= 30:
            return -50.0
        if age_days <= 90:
            return -30.0
        return 0.0

    def score_candidates(
        self,
        candidates: Iterable[PortalRecommendationCandidate],
        *,
        tenant_id: int,
        user_id: int,
        has_domain_signal: bool,
        has_interest_signal: bool,
        read_at_by_key: dict[tuple[int, int], datetime] | None = None,
        config: PortalRecommendationScoringConfig | None = None,
        now: datetime | None = None,
        config_version: int | None = None,
    ) -> list[PortalRecommendationCandidate]:
        del config_version  # It must not perturb the stable order within a cycle.
        config = config or PortalRecommendationScoringConfig()
        config.validate()
        now = now or datetime.now(timezone.utc)
        read_at_by_key = read_at_by_key or {}

        active_weights: list[tuple[str, float]] = []
        if has_domain_signal:
            active_weights.append(("domain_score", self.DOMAIN_WEIGHT))
        if has_interest_signal:
            active_weights.append(("interest_score", self.INTEREST_WEIGHT))
        active_weights.extend(
            (("hot_score", self.HOT_WEIGHT), ("fresh_score", self.FRESH_WEIGHT))
        )
        denominator = sum(weight for _, weight in active_weights)

        scored: list[PortalRecommendationCandidate] = []
        for candidate in candidates:
            weighted_score = sum(
                self._clamp_feature(getattr(candidate, feature)) * weight for feature, weight in active_weights
            )
            base_score = weighted_score / denominator
            penalty = self._read_penalty(read_at_by_key.get(candidate.key), now)
            scored.append(
                replace(
                    candidate,
                    base_score=base_score,
                    read_penalty=penalty,
                    final_score=base_score + penalty,
                )
            )

        scored.sort(key=lambda item: (-item.final_score, -item.file_id, -item.space_id))
        cycle_bucket = now.date().toordinal() // config.stable_shuffle_cycle_days
        return self._stable_shuffle_groups(
            scored,
            tenant_id=tenant_id,
            user_id=user_id,
            cycle_bucket=cycle_bucket,
            score_gap=config.stable_shuffle_score_gap,
        )

    @staticmethod
    def _stable_shuffle_groups(
        candidates: Sequence[PortalRecommendationCandidate],
        *,
        tenant_id: int,
        user_id: int,
        cycle_bucket: int,
        score_gap: float,
    ) -> list[PortalRecommendationCandidate]:
        result: list[PortalRecommendationCandidate] = []
        index = 0
        while index < len(candidates):
            anchor_score = candidates[index].final_score
            end = index + 1
            while end < len(candidates) and anchor_score - candidates[end].final_score <= score_gap:
                end += 1
            group = list(candidates[index:end])
            group.sort(
                key=lambda item: hashlib.sha256(
                    f"{tenant_id}:{user_id}:{cycle_bucket}:{item.space_id}:{item.file_id}".encode()
                ).digest()
            )
            result.extend(group)
            index = end
        return result

    async def select_authorized_top_n(
        self,
        ordered_candidates: Sequence[PortalRecommendationCandidate],
        *,
        top_n: int,
        build_permission_context: PermissionContextFactory,
        check_permission_batch: PermissionBatchChecker,
        batch_size: int = 10,
        max_checks: int = 200,
        budget_seconds: float = 0.7,
        state: PortalRecommendationAuthorizationState | None = None,
    ) -> list[PortalRecommendationCandidate]:
        if top_n <= 0:
            return []
        state = state or PortalRecommendationAuthorizationState()
        if state.started_at is None:
            state.started_at = self._clock()
        confirmed = [item for item in ordered_candidates if state.decisions.get(item.key)][:top_n]
        if (
            state.unavailable
            or state.checks >= max_checks
            or self._clock() - state.started_at >= budget_seconds
        ):
            return confirmed
        if not state.context_initialized:
            try:
                state.permission_context = await build_permission_context()
                state.context_initialized = True
            except Exception:
                logger.warning("portal recommendation permission context unavailable; returning safe empty result")
                state.unavailable = True
                return []

        selected: list[PortalRecommendationCandidate] = []
        cursor = 0
        while cursor < len(ordered_candidates) and state.checks < max_checks and len(selected) < top_n:
            if self._clock() - state.started_at >= budget_seconds:
                break
            batch = list(
                ordered_candidates[
                    cursor : min(cursor + batch_size, cursor + max_checks - state.checks)
                ]
            )
            if not batch:
                break
            cursor += len(batch)
            unseen = [item for item in batch if item.key not in state.decisions]
            state.checks += len(unseen)

            fast_allowed = {item.key for item in unseen if item.eligible and item.is_public and item.normal_acl}
            for key in fast_allowed:
                state.decisions[key] = True
            for item in unseen:
                if not item.eligible:
                    state.decisions[item.key] = False
            needs_check = [
                item
                for item in unseen
                if item.eligible and not (item.is_public and item.normal_acl)
            ]
            checked_result: dict[tuple[int, int], bool | Exception] = {}
            engine_unavailable = False
            if needs_check:
                try:
                    maybe_result = check_permission_batch(state.permission_context, needs_check)
                    checked_result = (
                        await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
                    )
                except PortalRecommendationPermissionContextUnavailable:
                    logger.warning("portal recommendation permission engine unavailable; stopping safe selection")
                    engine_unavailable = True
                    state.unavailable = True
                except Exception:
                    logger.warning("portal recommendation permission batch failed closed")
                    checked_result = {}

            for item in needs_check:
                state.decisions[item.key] = checked_result.get(item.key) is True

            for item in batch:
                if state.decisions.get(item.key) is True:
                    selected.append(item)
                if len(selected) >= top_n:
                    break
            if engine_unavailable:
                break
        return selected
