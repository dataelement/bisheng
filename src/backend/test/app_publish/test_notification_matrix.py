"""T068 — the AC-64 reach table (and the AC-08 criterion, re-deliberated).

Two settled decisions, machine-checked so that reversing one means deleting a
test that says why. They share a file because they share a shape: both are
claims that something is **deliberately absent**, and absence is the one thing a
behavioural test cannot observe.

AC-64 is two claims, and only one of them is testable by watching a release run:

1. **These events reach these people.** Covered behaviourally elsewhere —
   ``test_publish_notification.py`` drives approve / reject / withdraw through
   the real engine, ``test_release_terminal_states.py`` drives the
   delete-cancel, and ``test_notification_table_acceptance.py`` (F056 T033)
   takes the cross-package census. Repeating any of that here would be a second
   copy that can disagree with the first.
2. **These events reach nobody, and there is no mechanism that would make them.**
   That is what this file is for. A silent row cannot be observed by running
   anything: "nobody was told" and "this branch happened not to run" look
   identical. So the table below is asserted *structurally* — against the
   action codes that exist, the senders that exist, and the scheduled work that
   exists — and it is the whole table, not the rows one feature happens to own.

The row that motivated a separate file is the last one: **催办 / 超时提醒 / 升级
机制 are not being done** (design §8「明确不做」). Nothing fails when a reminder
mechanism is absent; it is the kind of decision that gets quietly reversed by
the first person who thinks "an approval sitting for three days should ping
somebody", and then the platform has a scheduler nobody specified, sending copy
nobody wrote, to recipients nobody chose. The assertion is that there is no
periodic task, no reminder action code and no deadline field anywhere on this
path — so reversing the decision means deleting a test that says why.

**AC-08 re-deliberated (2026-09-16).** The AC asks the precheck to refuse a
package that depends on middleware outside the hosting contract. Design D4 chose
*not* to do that statically — reading ``requirements.txt`` to guess "does this
connect to a MySQL" is a hallucination-grade criterion: the dependency is
present in every application that ever touched a dataframe library, absent from
every application that builds its DSN from an environment variable, and wrong in
both directions. The criterion is the **startup probe**: an application that
cannot reach the database it brought does not become ready, and the refusal
(16228) carries the conversion guidance the AC actually asks for. This round
re-checked that choice against what shipped, and the last class below is what it
came to: the guidance exists, names all three middleware kinds and the variable
that replaces them, and no scanner has grown next to it.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

#: Repository root, from ``src/backend/test/app_publish/``.
_BACKEND = Path(__file__).resolve().parents[2]
_CLIENT_LOCALES = _BACKEND.parent / "frontend" / "client" / "src" / "locales"
_CLIENT_LANGUAGES = ("zh-Hans", "en", "ja")

#: Design §4.2 ⑦ — every event of a hosted-app release that reaches a person,
#: with the side that sends it. "engine" rows are the approval centre's own
#: (决议-11): F055 must not send a second copy, and the engine must not stop
#: sending them. Both halves are asserted below.
REACH_TABLE: tuple[tuple[str, str, str], ...] = (
    ("审批单生成", "approval_task_pending", "f055"),
    ("审批通过", "approval_instance_approved", "engine"),
    ("审批驳回", "approval_task_rejected", "engine"),
    ("审批被撤回", "approval_instance_withdrawn", "engine"),
    ("应用被删除致审批取消", "approval_instance_cancelled", "engine"),
    ("待上线(资源不足)", "app_publish_pending_capacity", "f055"),
    ("待上线(上线失败)", "app_publish_deploy_failed", "f055"),
    ("迭代未上线(线上版本仍在服务)", "app_publish_iteration_failed", "f055"),
)

#: The rows AC-64 settles as **不主动提示**, each with the reason it is silent.
#: Kept as data rather than prose so that adding a sender for one of them has to
#: come here and delete its row — which is where the reason is.
SILENT_ROWS: tuple[tuple[str, str], ...] = (
    (
        "资源释放后可手动上线",
        "没有事件可以触发它: 没有人在等某个时刻, 容量是慢慢空出来的。发布面自查, 「手动上线」按钮就在状态区旁边。",
    ),
    (
        "能力被收回",
        "界面靠「调用失败 + 已失效标记」当场说清楚 (AC-53 / AC-63); 一条几小时后"
        "到达、脱离上下文的站内信只会让人去翻自己没做过的操作。",
    ),
    (
        "数据表迁移被拒且应用本来就不在线",
        "这次发布整体失败, 与构建失败 / 探活失败同族 —— 那两类也不发站内信, "
        "都由发布面与 bisheng deploy 报告。应用在线时走 iteration_failed 那一行, "
        "因为那条文案说的正是「新版本未能上线, 线上版本仍在服务」。",
    ),
)

#: What a reminder / escalation mechanism would be called, in either language.
#: Matched against identifiers and string literals on the publish + approval
#: notification path.
#:
#: Short fragments were tried and removed: ``nag`` is inside ``manager`` and
#: ``sla`` inside plenty of prose, and a pattern that cries wolf is a pattern
#: somebody deletes rather than reads.
REMINDER_WORDS = re.compile(
    r"remind|escalat|overdue|deadline|催办|催促|超时提醒|逾期",
    re.IGNORECASE,
)

#: Files where ``deadline`` means **a resource's lifetime**, not a message to a
#: person. AC-28 requires an approval-time preview instance to be reclaimed once
#: its window passes, so the word is load-bearing there and the thing it names
#: has no recipient, no copy and no schedule — the three parts that would make
#: it the reminder mechanism design §8 refuses. Narrowed here rather than
#: dropping ``deadline`` from the pattern, because an *approval* deadline is
#: exactly what the word must keep catching everywhere else.
_DEADLINE_IS_A_LIFETIME = frozenset({"preview_instance_service.py"})


def _module(path: str):
    import importlib

    return importlib.import_module(path)


def _declared_action_codes() -> set[str]:
    module = _module("bisheng.app_publish.domain.services.publish_notification_service")
    return {value for name, value in vars(module).items() if name.startswith("ACTION_") and isinstance(value, str)}


def _package_root(name: str) -> Path:
    module = _module(name)
    return Path(module.__file__).parent if module.__file__ else Path(next(iter(module.__path__)))


def _string_literals(root: Path) -> list[tuple[Path, str]]:
    """Every string literal and identifier in a package, with the file it is in."""
    found: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((path, node.value))
            elif isinstance(node, ast.Name):
                found.append((path, node.id))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.append((path, node.name))
    return found


# ---------------------------------------------------------------------------
# the sending half
# ---------------------------------------------------------------------------


class TestEverySendingRowHasExactlyOneSender:
    @pytest.mark.parametrize(
        ("event", "action_code"),
        [(event, code) for event, code, owner in REACH_TABLE if owner == "f055"],
    )
    def test_an_f055_row_is_declared_as_a_constant(self, event, action_code):
        """A row F055 sends has a named constant, so its one sender is findable.

        Spelling the code inline at the call site would make "who sends this"
        answerable only by grep, and the answer would silently become "two
        places" the first time somebody copies the call.
        """
        assert action_code in _declared_action_codes(), event

    @pytest.mark.parametrize(
        ("event", "action_code"),
        [(event, code) for event, code, owner in REACH_TABLE if owner == "engine"],
    )
    def test_an_engine_row_is_not_re_sent_by_the_publish_side(self, event, action_code):
        """决议-11: the approval centre already told them. A copy here doubles
        every message the owner receives, and nothing fails when it does."""
        assert action_code not in _declared_action_codes(), event

    def test_the_declared_codes_are_exactly_the_table(self):
        """No extra constant, either.

        A constant is where the next person looks for permission to send
        something; an unused ``ACTION_CAPABILITY_REVOKED`` is how 「不主动提示」
        turns into 「有人接上了」.
        """
        assert _declared_action_codes() == {code for _, code, owner in REACH_TABLE if owner == "f055"}

    @pytest.mark.parametrize("language", _CLIENT_LANGUAGES)
    def test_every_f055_row_has_copy_in_every_language(self, language):
        """The client renders ``com_notifications_action_{code}``; a missing key
        shows the raw action code to the recipient (design 坑 24 neighbourhood)."""
        payload = json.loads((_CLIENT_LOCALES / language / "translation.json").read_text(encoding="utf-8"))
        missing = [
            code
            for _, code, owner in REACH_TABLE
            if owner == "f055" and f"com_notifications_action_{code}" not in payload
        ]
        assert not missing, f"{language}: no copy for {missing}"


# ---------------------------------------------------------------------------
# the silent half
# ---------------------------------------------------------------------------


class TestTheSilentRowsStaySilent:
    @pytest.mark.parametrize(("row", "reason"), SILENT_ROWS)
    def test_no_action_code_exists_for_a_silent_row(self, row, reason):
        """Each silent row, checked against the vocabulary that would carry it."""
        words = re.compile(r"capabilit|revoke|resource_release|manual_publish|schema_migration", re.IGNORECASE)
        offenders = [code for code in _declared_action_codes() if words.search(code)]

        assert not offenders, f"{row} grew an action code ({offenders}); the reason it has none: {reason}"

    def test_a_schema_migration_refusal_notifies_only_an_online_application(self):
        """The third silent row, at its one call site.

        The online case reuses ``iteration_failed`` because that copy is exactly
        true; the offline case sends nothing. Read off the source because the
        branch is the decision — a behavioural test of the offline case can only
        show that one run stayed quiet.
        """
        import inspect

        from bisheng.app_publish.domain.services.publish_online_service import PublishOnlineService

        source = inspect.getsource(PublishOnlineService._settle_schema_failure)

        assert "if online:" in source
        assert 'reason_kind="iteration_failed"' in source
        assert "app_publish_deploy_failed" not in source, (
            "the parked copy tells the reader to press 「手动上线」, and a failed "
            "migration is not parked — there is no button"
        )


# ---------------------------------------------------------------------------
# 催办 / 超时提醒 / 升级机制 —— 明确不做 (design §8)
# ---------------------------------------------------------------------------


class TestNoReminderMechanism:
    """The decision, machine-checked from three directions.

    Three, because each one alone can be satisfied while the mechanism exists:
    a reminder could live in a Celery beat schedule with an innocuous name, in a
    notification helper with no schedule at all, or in a scenario field that
    some *other* service reads on a timer.
    """

    def test_no_periodic_task_watches_a_pending_release_or_approval(self):
        """Neither worker package declares a schedule, and neither is in Beat.

        A publish pipeline task and an outbox task both exist; both are
        dispatched by an event (`delay` at the moment something happened).
        Nothing in either package runs on a clock, which is the shape a
        reminder would need.
        """
        for package in ("bisheng.worker.app_publish", "bisheng.worker.approval"):
            for path in sorted(_package_root(package).rglob("*.py")):
                source = path.read_text(encoding="utf-8")
                assert "crontab" not in source, path
                assert "beat_schedule" not in source, path
                assert "periodic" not in source.lower(), path

    @pytest.mark.parametrize(
        "package",
        [
            "bisheng.app_publish.domain.services",
            "bisheng.approval.domain.services",
        ],
    )
    def test_no_reminder_vocabulary_on_the_publish_or_approval_path(self, package):
        """No identifier and no literal that would be a reminder.

        Deliberately a word list rather than a behavioural test: the thing being
        asserted is that a *feature* is absent, and absence has no behaviour to
        observe. If this ever fails on an innocent word, the fix is to narrow
        the pattern in the same change that explains why the word is there.
        """
        offenders = sorted(
            {
                f"{path.name}:{text[:60]}"
                for path, text in _string_literals(_package_root(package))
                if REMINDER_WORDS.search(text) and path.name not in _DEADLINE_IS_A_LIFETIME
            }
        )

        assert not offenders, (
            "催办 / 超时提醒 / 升级机制 are explicitly not done (design §8). "
            f"Found: {offenders}. Adding one means a scheduler, three-language copy and "
            "a recipient rule — all of which need a decision first."
        )

    def test_the_approval_scenario_carries_no_deadline(self):
        """The scenario model has nowhere to put a timeout, so no other service
        can grow a timer that reads one."""
        from bisheng.approval.domain.models.approval_scenario import ApprovalScenario

        fields = set(ApprovalScenario.model_fields)

        assert not [name for name in fields if REMINDER_WORDS.search(name)], sorted(fields)


# ---------------------------------------------------------------------------
# AC-08 —— 判据仍由探活兜底 (design D4, 复议于 2026-09-16)
# ---------------------------------------------------------------------------


class TestAc08StaysProbeBased:
    """The AC's *remedy* is what has to exist; the AC's *detector* is the probe.

    Worth pinning as a pair, because each half is useless alone: a refusal with
    no guidance leaves the developer guessing what a hosted application may
    depend on, and guidance attached to a check nobody runs never reaches
    anybody.
    """

    def test_the_probe_refusal_carries_the_conversion_guidance(self):
        """All three middleware kinds the hosting contract excludes, by name,
        plus the variable that replaces the first of them."""
        from bisheng.app_publish.domain.services.precheck_service import PROBE_HINTS

        joined = " ".join(PROBE_HINTS)

        for word in ("数据库", "消息队列", "缓存", "BISHENG_APP_DB_URL"):
            assert word in joined, f"AC-08 guidance lost {word!r}"

    def test_the_guidance_is_attached_to_every_probe_failure(self):
        """Not to one branch of it. A second raise site with its own hints is
        how half the refusals would stop explaining themselves."""
        import inspect

        from bisheng.app_publish.domain.services import precheck_service

        source = inspect.getsource(precheck_service)
        # The bare name also appears at its definition and in prose; only the
        # call form counts, and ``AppStartupProbeFailedError(`` with a paren
        # only ever appears at a raise site (the import has none).
        raises = source.count("AppStartupProbeFailedError(")

        assert raises >= 1
        assert raises == source.count("hints=list(PROBE_HINTS)"), (
            "every AppStartupProbeFailedError must carry PROBE_HINTS; a bare one "
            "refuses the release without saying what to change"
        )

    def test_no_static_dependency_scanner_grew_next_to_it(self):
        """D4's actual decision: the package's declared dependencies are never
        read to guess what it connects to.

        The precheck does open the package (the secret scan walks it) and it
        does *mention* ``requirements.txt`` — in the hints of a build failure,
        where it is the right advice. What must not exist is a read of one for
        a middleware verdict, so the check is against the reading verbs rather
        than against the word.
        """
        from pathlib import Path

        from bisheng.app_publish.domain.services import precheck_service

        source = Path(precheck_service.__file__).read_text(encoding="utf-8")
        reads = re.compile(
            r"(open|read_text|read_bytes|joinpath|glob|parse)\s*\([^)]*(requirements|pyproject|package\.json)",
            re.IGNORECASE,
        )

        assert not reads.findall(source), (
            "a dependency manifest is being read in the precheck. Guessing middleware from "
            "declared dependencies is the criterion D4 rejected — it is wrong in both directions."
        )
