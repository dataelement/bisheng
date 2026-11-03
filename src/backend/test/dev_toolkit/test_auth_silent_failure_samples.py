"""F057 T039 — the evaluation samples for auth's silent failure point (AC-29).

The acceptance target is a model-judged rate: over ≥5 product-name-neutral app
requests, an agent that has read the「平台能力接线」pack must stop building its
own sign-in and read the platform-injected identity instead, 5/5. That judgement
is run by hand (or by the skill-creator evaluator) and recorded in tasks.md.

What a deterministic test *can* pin — and what silently rots otherwise — is the
sample set itself: enough of them, neutral phrasing (a sample naming the product
would test name-matching rather than intent), each carrying an identity intent
the pack actually speaks to, and each stating both halves of the judgement so a
later run cannot quietly move the goalposts. The last test closes the loop back
onto the chapter: the wrong answers the samples predict are the ones the chapter
names explicitly.
"""

from __future__ import annotations

import re
from pathlib import Path

from bisheng.dev_toolkit.domain.services.artifact_service import SKILLS_DIR

FIXTURE = Path(__file__).parent / "fixtures" / "auth_silent_failure_samples.md"
SKILL_MD = SKILLS_DIR / "platform-wiring" / "SKILL.md"

# AC-19's rule, inherited: a sample must not name the product.
PRODUCT_NAMES = ("毕昇", "bisheng", "BiSheng", "BISHENG")

# The kind of intent that makes "build a login page" the naive answer. A sample
# without one of these is not testing the silent failure point at all.
IDENTITY_INTENT = ("谁", "登录", "当前用户", "身份", "部门", "权限", "自己", "本人", "同事")


def _samples() -> list[dict[str, str]]:
    """``## `` sections with their ``- key: value`` lines (full-width colon)."""
    text = FIXTURE.read_text(encoding="utf-8")
    samples = []
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        title, _, rest = block.partition("\n")
        fields = dict(re.findall("^- ([^\uff1a]+)\uff1a(.+)$", rest, re.MULTILINE))
        fields["title"] = title.strip()
        samples.append(fields)
    return samples


def test_at_least_five_samples():
    assert len(_samples()) >= 5


def test_samples_are_product_name_neutral():
    for sample in _samples():
        blob = " ".join(sample.values())
        assert not any(name in blob for name in PRODUCT_NAMES), f"product name in sample: {sample['title']}"


def test_each_sample_carries_identity_intent():
    for sample in _samples():
        need = sample.get("需求", "")
        assert need, f"sample without a 需求 line: {sample['title']}"
        assert any(term in need for term in IDENTITY_INTENT), f"no identity intent: {need!r}"


def test_each_sample_states_both_halves_of_the_judgement():
    """Without the "read the pack" half, a run could score anything as a pass."""
    for sample in _samples():
        assert sample.get("未读包的典型产出"), f"missing naive-output criterion: {sample['title']}"
        assert sample.get("读包后应有产出"), f"missing post-read criterion: {sample['title']}"


def test_the_pack_names_the_wrong_answers_the_samples_predict():
    """The samples' naive outputs must be exactly what the chapter forbids by name."""
    # Split on `## ` at line start only — a plain `"## "` split also cuts at
    # every `### ` sub-heading and would silently shrink the chapter to its
    # first paragraph, making the rest of this assertion vacuous.
    chapter = re.split(r"^## ", SKILL_MD.read_text(encoding="utf-8"), flags=re.MULTILINE)[1]
    for forbidden in ("登录页", "校验密码", "cookie", "解析 JWT"):
        assert forbidden in chapter, forbidden
    # And the positive answer is one call, stated in the same chapter.
    assert "auth.current_user()" in chapter
