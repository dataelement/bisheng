"""F053 T040 — the「部署纳管」pack triggers on neutral deploy phrasings (AC-22①).

The acceptance target is a 100% trigger rate over ≥10 product-name-neutral deploy
phrasings, measured by a model deciding whether to consult the skill from its
description alone (the skill-creator description-optimizer does that end-to-end).
What a deterministic repo test *can* pin — and what regresses silently otherwise
— is the two structural preconditions that make that rate reachable:

* the sample set is real (≥10) and **neutral** (AC-19: no product name, or the
  phrasing would be testing name-matching, not intent-matching);
* every sample carries deploy intent the skill's description also speaks, so the
  description covers the space the samples span.
"""

from __future__ import annotations

import re
from pathlib import Path

from bisheng.dev_toolkit.domain.services.artifact_service import SKILLS_DIR

FIXTURE = Path(__file__).parent / "fixtures" / "skill_trigger_samples.md"
SKILL_MD = SKILLS_DIR / "deploy-hosting" / "SKILL.md"

# Deploy intent expressed the way people actually say it — none of these name a
# product. A sample is on-topic if it uses at least one.
DEPLOY_INTENT = (
    "部署",
    "发布",
    "上线",
    "应用平台",
    "应用广场",
    "应用中心",
    "托管",
    "deploy",
    "publish",
    "app platform",
    "app hub",
)

# Vocabulary the description must speak so it would trigger on these phrasings.
CORE_DESCRIPTION_TERMS = ("部署", "发布", "上线", "应用平台", "应用广场", "deploy")

# AC-19: the trigger must not be bound to any product name.
PRODUCT_NAMES = ("毕昇", "bisheng", "BiSheng", "BISHENG")


def _samples() -> list[str]:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    return [line[2:].strip() for line in lines if line.startswith("- ")]


def _skill_description() -> str:
    text = SKILL_MD.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    match = re.search(r"description:\s*>-?\s*\n(.*?)(?:\nmetadata:|\n[a-z-]+:\s)", front, re.DOTALL)
    return match.group(1) if match else front


def test_at_least_ten_samples():
    assert len(_samples()) >= 10


def test_samples_are_product_name_neutral():
    # If a sample said "毕昇", triggering on it would prove name-matching, not the
    # intent-matching AC-19 actually requires.
    for sample in _samples():
        assert not any(name in sample for name in PRODUCT_NAMES), f"product name in sample: {sample!r}"


def test_every_sample_carries_deploy_intent():
    for sample in _samples():
        assert any(term in sample for term in DEPLOY_INTENT), f"no deploy intent in sample: {sample!r}"


def test_description_covers_the_deploy_vocabulary():
    description = _skill_description()
    missing = [term for term in CORE_DESCRIPTION_TERMS if term not in description]
    assert not missing, f"skill description missing trigger vocabulary: {missing}"
