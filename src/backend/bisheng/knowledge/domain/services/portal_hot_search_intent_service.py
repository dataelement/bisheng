"""LLM intent grouping for the portal hot-search pipeline (F048)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import HotSearchIntentGroup
from bisheng.knowledge.domain.services.portal_hot_search_scoring_service import intent_key_for

LLMInvoke = Callable[[str], str]

GROUP_PROMPT = """你是搜索意图分析助手。将下列搜索词按意图分组。
规则：
1. 意思相同但表述不同的合并为一组
2. 主体不同的必须分开（如"设备A检修"与"设备B检修"）
3. 纠正明显错别字
4. 只输出 JSON：{{"groups":[{{"intent_id":"g1","canonical_query":"...","members":["..."]}}]}}

搜索词：
{queries}"""


@dataclass
class IntentGroupingResult:
    groups: list[HotSearchIntentGroup]
    degraded: bool


class PortalHotSearchIntentService:
    """Groups candidate queries by intent via the LLM, with safe degradation.

    On any LLM/parse failure it falls back to identity grouping (one group per
    distinct query) so the batch always produces a result.
    """

    def __init__(self, llm_invoke: LLMInvoke | None = None) -> None:
        self._llm_invoke = llm_invoke

    def group(self, queries: Sequence[str]) -> IntentGroupingResult:
        distinct = list(dict.fromkeys(q for q in queries if q))
        if not distinct:
            return IntentGroupingResult(groups=[], degraded=False)
        if self._llm_invoke is None:
            return IntentGroupingResult(groups=self._identity_groups(distinct), degraded=True)
        try:
            response = self._llm_invoke(GROUP_PROMPT.format(queries="\n".join(distinct)))
            groups = self._parse_groups(response, distinct)
            if not groups:
                raise ValueError("empty groups parsed from LLM response")
            return IntentGroupingResult(groups=groups, degraded=False)
        except Exception:
            return IntentGroupingResult(groups=self._identity_groups(distinct), degraded=True)

    @staticmethod
    def _identity_groups(distinct: Sequence[str]) -> list[HotSearchIntentGroup]:
        return [
            HotSearchIntentGroup(
                intent_key=intent_key_for(query),
                canonical_query=query,
                member_queries=[query],
            )
            for query in distinct
        ]

    @staticmethod
    def _parse_groups(response: str, distinct: Sequence[str]) -> list[HotSearchIntentGroup]:
        payload = _extract_json_object(response)
        raw_groups = payload.get("groups") if isinstance(payload, dict) else None
        if not isinstance(raw_groups, list):
            raise ValueError("groups is not a list")
        distinct_set = set(distinct)
        groups: list[HotSearchIntentGroup] = []
        assigned: set[str] = set()
        for raw in raw_groups:
            if not isinstance(raw, dict):
                continue
            canonical = str(raw.get("canonical_query") or "").strip()
            members_raw = raw.get("members")
            members = [str(m).strip() for m in members_raw if str(m).strip()] if isinstance(members_raw, list) else []
            # Only keep members that were actually part of the input set.
            members = [m for m in members if m in distinct_set and m not in assigned]
            if not canonical or not members:
                continue
            assigned.update(members)
            groups.append(
                HotSearchIntentGroup(
                    intent_key=intent_key_for(canonical),
                    canonical_query=canonical,
                    member_queries=members,
                )
            )
        # Any query the LLM dropped becomes its own single-member group.
        for query in distinct:
            if query not in assigned:
                groups.append(
                    HotSearchIntentGroup(
                        intent_key=intent_key_for(query),
                        canonical_query=query,
                        member_queries=[query],
                    )
                )
                assigned.add(query)
        return groups


def _extract_json_object(text: str) -> dict:
    if not text:
        raise ValueError("empty LLM response")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found")
    return json.loads(match.group(0))
