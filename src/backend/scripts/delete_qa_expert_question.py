#!/usr/bin/env python3
"""Delete one Expert QA question and all dependent rows.

This script is for manual maintenance of the Expert QA module. It deletes a
single ``qa_question`` row by ID and cleans up dependent rows from answers,
comments / follow-ups, votes, and notifications so no orphan rows are left.

Usage from ``src/backend``:

    PYTHONPATH=./ .venv/bin/python scripts/delete_qa_expert_question.py 123
    PYTHONPATH=./ .venv/bin/python scripts/delete_qa_expert_question.py 123 --apply
    bash scripts/delete_qa_expert_question.sh 123 --apply

Default mode is dry-run. Pass ``--apply`` to actually delete data.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import delete as sa_delete  # noqa: E402
from sqlmodel import func, select  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.qa_expert import (  # noqa: E402
    Answer,
    AnswerVote,
    Comment,
    CommentVote,
    QANotification,
    Question,
    QuestionVote,
)


@dataclass(frozen=True)
class DeletePlan:
    question_id: int
    title: str
    created_by: str | None
    created_at: datetime | None
    answer_ids: tuple[int, ...]
    comment_ids: tuple[int, ...]
    counts: dict[str, int]


def _scalar_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, tuple):
        value = value[0] if value else 0
    return int(value or 0)


async def _count(session, model, *where_clauses) -> int:
    result = await session.exec(select(func.count(model.id)).where(*where_clauses))
    return _scalar_int(result.first())


async def _build_plan(session, question_id: int) -> DeletePlan | None:
    question_result = await session.exec(select(Question).where(Question.id == question_id))
    question = question_result.first()
    if question is None:
        return None

    answer_result = await session.exec(select(Answer).where(Answer.question_id == question_id))
    answers = answer_result.all()
    answer_ids = tuple(answer.id for answer in answers if answer.id is not None)

    comment_result = await session.exec(select(Comment).where(Comment.question_id == question_id))
    comments = comment_result.all()
    comment_ids = tuple(comment.id for comment in comments if comment.id is not None)

    counts = {
        "qa_question": 1,
        "qa_answer": len(answer_ids),
        "qa_comment": len(comment_ids),
        "qa_question_vote": await _count(session, QuestionVote, QuestionVote.question_id == question_id),
        "qa_notification": await _count(session, QANotification, QANotification.question_id == question_id),
        "qa_answer_vote": 0,
        "qa_comment_vote": 0,
    }
    if answer_ids:
        counts["qa_answer_vote"] = await _count(session, AnswerVote, AnswerVote.answer_id.in_(answer_ids))
    if comment_ids:
        counts["qa_comment_vote"] = await _count(session, CommentVote, CommentVote.comment_id.in_(comment_ids))

    return DeletePlan(
        question_id=question_id,
        title=question.title,
        created_by=question.created_by,
        created_at=question.created_at,
        answer_ids=answer_ids,
        comment_ids=comment_ids,
        counts=counts,
    )


def _print_plan(plan: DeletePlan, apply: bool) -> None:
    mode = "apply" if apply else "dry-run"
    print(f"Mode: {mode}")
    print(f"Question ID: {plan.question_id}")
    print(f"Title: {plan.title}")
    print(f"Created by: {plan.created_by or '-'}")
    print(f"Created at: {plan.created_at.isoformat() if plan.created_at else '-'}")
    print()
    print("Rows to delete:")
    for table_name, count in plan.counts.items():
        print(f"  - {table_name}: {count}")
    print()
    if plan.answer_ids:
        print(f"Answer IDs: {', '.join(str(item) for item in plan.answer_ids)}")
    if plan.comment_ids:
        print(f"Comment IDs: {', '.join(str(item) for item in plan.comment_ids)}")
    if not apply:
        print()
        print("Dry-run only. Re-run with --apply to actually delete these rows.")


async def _delete_plan(session, plan: DeletePlan) -> None:
    if plan.comment_ids:
        await session.exec(sa_delete(CommentVote).where(CommentVote.comment_id.in_(plan.comment_ids)))
    if plan.answer_ids:
        await session.exec(sa_delete(AnswerVote).where(AnswerVote.answer_id.in_(plan.answer_ids)))

    await session.exec(sa_delete(QuestionVote).where(QuestionVote.question_id == plan.question_id))
    await session.exec(sa_delete(QANotification).where(QANotification.question_id == plan.question_id))
    await session.exec(sa_delete(Comment).where(Comment.question_id == plan.question_id))
    await session.exec(sa_delete(Answer).where(Answer.question_id == plan.question_id))
    await session.exec(sa_delete(Question).where(Question.id == plan.question_id))
    await session.commit()


async def delete_question(question_id: int, apply: bool) -> int:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            plan = await _build_plan(session, question_id)
            if plan is None:
                print(f"Question question_id={question_id} not found.", file=sys.stderr)
                return 1

            _print_plan(plan, apply)
            if not apply:
                return 0

            await _delete_plan(session, plan)
            print()
            print(f"Deleted Expert QA question question_id={question_id} and dependent rows.")
            return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question_id", type=int, help="Expert QA question ID to delete")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete rows. Default is dry-run preview.",
    )
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    try:
        if args.question_id <= 0:
            print("question_id must be a positive integer.", file=sys.stderr)
            return 1
        return await delete_question(args.question_id, args.apply)
    finally:
        await close_app_context()
        gc.collect()
        await asyncio.sleep(0)


def main() -> int:
    return asyncio.run(_amain(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
