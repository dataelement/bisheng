from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

from bisheng.sensitive_word.domain.models.sensitive_word_policy import (
    SensitiveWordPolicy,
    SensitiveWordPolicyDao,
)
from bisheng.sensitive_word.domain.schemas import (
    SensitiveWordBusinessType,
    SensitiveWordCheckResult,
    SensitiveWordHit,
    SensitiveWordPolicyPayload,
    SensitiveWordPolicyResp,
    SensitiveWordScopeType,
)
from bisheng.sensitive_word.domain.services.ac_automaton import ACAutomaton

if TYPE_CHECKING:
    from bisheng.common.dependencies.user_deps import UserPayload

DEFAULT_AUTO_REPLY = '上传内容命中敏感词，已被系统拒绝。'
BUILTIN_WORDS_TYPE = 'builtin'
CUSTOM_WORDS_TYPE = 'custom'
WORD_SEPARATOR_RE = re.compile(r'[\r\n,，;；|]+')


class SensitiveWordPolicyService:
    _automaton_cache: Dict[Tuple, Tuple[ACAutomaton, Dict[str, str]]] = {}

    @staticmethod
    def _current_tenant_id(login_user: UserPayload) -> int:
        from bisheng.core.context.tenant import get_current_tenant_id

        return get_current_tenant_id() or login_user.tenant_id

    @classmethod
    def normalize_words(cls, text: str) -> List[str]:
        words: List[str] = []
        seen = set()
        for item in WORD_SEPARATOR_RE.split(text or ''):
            word = item.strip()
            if not word or word in seen:
                continue
            seen.add(word)
            words.append(word)
        return words

    @classmethod
    def normalize_words_types(cls, words_types: Iterable[str]) -> List[str]:
        allowed = {BUILTIN_WORDS_TYPE, CUSTOM_WORDS_TYPE}
        result: List[str] = []
        for item in words_types or []:
            if item in allowed and item not in result:
                result.append(item)
        return result

    @classmethod
    @lru_cache(maxsize=1)
    def load_builtin_words(cls) -> Tuple[str, ...]:
        words_file = Path(__file__).resolve().parents[1] / 'data' / 'words.txt'
        if not words_file.exists():
            return ()
        return tuple(cls.normalize_words(words_file.read_text(encoding='utf-8')))

    @classmethod
    def clear_cache(cls) -> None:
        cls._automaton_cache.clear()
        cls.load_builtin_words.cache_clear()

    @classmethod
    def default_response(cls, tenant_id: int, business_type: str) -> SensitiveWordPolicyResp:
        return SensitiveWordPolicyResp(
            tenant_id=tenant_id,
            business_type=SensitiveWordBusinessType(business_type),
            scope_type=SensitiveWordScopeType.TENANT,
            scope_id=str(tenant_id),
            enabled=False,
            words_types=[],
            custom_words='',
            auto_reply=DEFAULT_AUTO_REPLY,
            extra_config={},
        )

    @classmethod
    def to_response(cls, policy: Optional[SensitiveWordPolicy], tenant_id: int, business_type: str) -> SensitiveWordPolicyResp:
        if policy is None:
            return cls.default_response(tenant_id, business_type)
        return SensitiveWordPolicyResp(
            tenant_id=policy.tenant_id,
            business_type=SensitiveWordBusinessType(policy.business_type),
            scope_type=SensitiveWordScopeType(policy.scope_type),
            scope_id=policy.scope_id,
            enabled=bool(policy.enabled),
            words_types=cls.normalize_words_types(policy.words_types),
            custom_words=policy.custom_words or '',
            auto_reply=policy.auto_reply or DEFAULT_AUTO_REPLY,
            extra_config=policy.extra_config or {},
        )

    @classmethod
    async def aget_policy(cls, login_user: UserPayload, business_type: SensitiveWordBusinessType) -> SensitiveWordPolicyResp:
        tenant_id = cls._current_tenant_id(login_user)
        policy = await SensitiveWordPolicyDao.aget_policy(
            tenant_id=tenant_id,
            business_type=business_type.value,
            scope_type=SensitiveWordScopeType.TENANT.value,
            scope_id=str(tenant_id),
        )
        return cls.to_response(policy, tenant_id, business_type.value)

    @classmethod
    async def aupsert_policy(
        cls,
        login_user: UserPayload,
        business_type: SensitiveWordBusinessType,
        payload: SensitiveWordPolicyPayload,
    ) -> SensitiveWordPolicyResp:
        tenant_id = cls._current_tenant_id(login_user)
        policy = await SensitiveWordPolicyDao.aupsert_policy(
            tenant_id=tenant_id,
            business_type=business_type.value,
            enabled=payload.enabled,
            words_types=cls.normalize_words_types(payload.words_types),
            custom_words=payload.custom_words or '',
            auto_reply=(payload.auto_reply or DEFAULT_AUTO_REPLY)[:500],
            extra_config=payload.extra_config or {},
            operator_id=login_user.user_id,
            scope_type=SensitiveWordScopeType.TENANT.value,
            scope_id=str(tenant_id),
        )
        cls.clear_cache()
        return cls.to_response(policy, tenant_id, business_type.value)

    @classmethod
    def _resolve_words(cls, policy: Optional[SensitiveWordPolicy]) -> List[str]:
        if policy is None or not policy.enabled:
            return []
        words_types = cls.normalize_words_types(policy.words_types)
        words: List[str] = []
        if BUILTIN_WORDS_TYPE in words_types:
            words.extend(cls.load_builtin_words())
        if CUSTOM_WORDS_TYPE in words_types:
            words.extend(cls.normalize_words(policy.custom_words or ''))

        deduped: List[str] = []
        seen = set()
        for word in words:
            if word in seen:
                continue
            seen.add(word)
            deduped.append(word)
        return deduped

    @classmethod
    def is_effective(
        cls,
        tenant_id: int,
        business_type: SensitiveWordBusinessType,
        scope_type: SensitiveWordScopeType = SensitiveWordScopeType.TENANT,
        scope_id: Optional[str] = None,
    ) -> bool:
        policy = SensitiveWordPolicyDao.get_policy(
            tenant_id=tenant_id,
            business_type=business_type.value,
            scope_type=scope_type.value,
            scope_id=scope_id or str(tenant_id),
        )
        return bool(cls._resolve_words(policy))

    @classmethod
    def _build_cache_key(
        cls,
        tenant_id: int,
        business_type: str,
        scope_type: str,
        scope_id: str,
        policy: SensitiveWordPolicy,
        words: List[str],
        case_sensitive: bool,
    ) -> Tuple:
        words_digest = hashlib.sha256('\n'.join(words).encode('utf-8')).hexdigest()
        return (
            tenant_id,
            business_type,
            scope_type,
            scope_id,
            bool(policy.enabled),
            tuple(cls.normalize_words_types(policy.words_types)),
            case_sensitive,
            words_digest,
        )

    @classmethod
    def _get_automaton(
        cls,
        tenant_id: int,
        business_type: str,
        scope_type: str,
        scope_id: str,
        policy: SensitiveWordPolicy,
        words: List[str],
        case_sensitive: bool,
    ) -> Tuple[ACAutomaton, Dict[str, str]]:
        normalized_map: Dict[str, str] = {}
        normalized_words: List[str] = []
        for word in words:
            normalized = word if case_sensitive else word.lower()
            if not normalized or normalized in normalized_map:
                continue
            normalized_map[normalized] = word
            normalized_words.append(normalized)

        key = cls._build_cache_key(
            tenant_id,
            business_type,
            scope_type,
            scope_id,
            policy,
            normalized_words,
            case_sensitive,
        )
        cached = cls._automaton_cache.get(key)
        if cached:
            return cached
        automaton = ACAutomaton(normalized_words)
        cls._automaton_cache[key] = (automaton, normalized_map)
        return automaton, normalized_map

    @classmethod
    def check_text(
        cls,
        tenant_id: int,
        business_type: SensitiveWordBusinessType,
        text: str,
        scope_type: SensitiveWordScopeType = SensitiveWordScopeType.TENANT,
        scope_id: Optional[str] = None,
    ) -> SensitiveWordCheckResult:
        final_scope_id = scope_id or str(tenant_id)
        policy = SensitiveWordPolicyDao.get_policy(
            tenant_id=tenant_id,
            business_type=business_type.value,
            scope_type=scope_type.value,
            scope_id=final_scope_id,
        )
        words = cls._resolve_words(policy)
        if policy is None or not words or not text:
            return SensitiveWordCheckResult(enabled=False, hits=[], auto_reply=DEFAULT_AUTO_REPLY)

        extra_config = policy.extra_config or {}
        case_sensitive = bool(extra_config.get('case_sensitive', False))
        max_hits = extra_config.get('max_hits')
        automaton, normalized_map = cls._get_automaton(
            tenant_id,
            business_type.value,
            scope_type.value,
            final_scope_id,
            policy,
            words,
            case_sensitive,
        )
        scan_text = text if case_sensitive else text.lower()
        counter = automaton.find_all(scan_text)

        hits: List[SensitiveWordHit] = [
            SensitiveWordHit(word=normalized_map.get(word, word), count=count)
            for word, count in counter.items()
        ]
        if isinstance(max_hits, int) and max_hits > 0:
            hits = hits[:max_hits]
        return SensitiveWordCheckResult(
            enabled=True,
            hits=hits,
            auto_reply=policy.auto_reply or DEFAULT_AUTO_REPLY,
        )
