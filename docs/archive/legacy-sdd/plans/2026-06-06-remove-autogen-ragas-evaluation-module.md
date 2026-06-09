# Remove autogen/ragas & Rebuild Evaluation as DDD Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `bisheng_pyautogen` and `bisheng-ragas` (+`datasets`) dependencies and the temporary `langchain_compat.py` shim, reimplementing the single ragas metric in pure LangChain and relocating evaluation into a proper DDD module.

**Architecture:** Part 1 deletes dead autogen code. Part 2 builds `bisheng/evaluation/` (api + domain layers), reimplements `AnswerCorrectnessBisheng` as a LangChain function with byte-identical output, moves the multi-tenant `Evaluation` table (no DB migration), and updates the tenant-filter module list. Part 3 drops the dependencies and deletes the shim.

**Tech Stack:** Python 3.10, FastAPI, SQLModel, LangChain 1.x (`langchain_core`), `json-repair`, pytest (`asyncio_mode=auto`), uv.

Work on branch `feat/langchain-1x`. All commands run from `src/backend/` unless noted.

---

## File Structure

**Part 1 — delete**
- `bisheng_langchain/autogen_role/` (package)
- `bisheng_langchain/chains/autogen/` (package, `AutoGenChain`)

**Part 2 — new module `bisheng/evaluation/`**
- `evaluation/__init__.py`
- `evaluation/api/router.py` — APIRouter aggregator
- `evaluation/api/endpoints/evaluation.py` — 5 endpoints (from `api/v1/evaluation.py`)
- `evaluation/domain/models/evaluation.py` — `Evaluation` table + `ExecType`/`EvaluationTaskStatus`
- `evaluation/domain/schemas/evaluation.py` — `EvaluationBase`/`EvaluationCreate`/`EvaluationRead`
- `evaluation/domain/repositories/evaluation_repository.py` — replaces `EvaluationDao`
- `evaluation/domain/services/evaluation_service.py` — orchestration (from `api/services/evaluation.py`)
- `evaluation/domain/services/answer_correctness.py` — NEW LangChain metric
- `test/evaluation/test_answer_correctness.py`, `test/evaluation/test_evaluation_repository.py`

**Part 2 — modify**
- `bisheng/core/database/tenant_filter.py` — module-list path
- `bisheng/api/router.py` — register router
- `bisheng/api/v1/__init__.py` — deregister old route

**Part 2 — delete after move**
- `bisheng/api/v1/evaluation.py`, `bisheng/api/services/evaluation.py`, `bisheng/database/models/evaluation.py`

**Part 3 — cleanup**
- `bisheng_langchain/rag/scoring/ragas_score.py` (delete)
- `bisheng_langchain/langchain_compat.py` (delete) + its imports in both `__init__.py`
- `pyproject.toml` — remove `bisheng_pyautogen`, `bisheng-ragas`, `datasets`

---

## Part 1 — Remove `bisheng_pyautogen`

### Task 1: Delete autogen packages and references

**Files:**
- Delete: `bisheng_langchain/autogen_role/`, `bisheng_langchain/chains/autogen/`
- Modify: `bisheng_langchain/chains/__init__.py`, `bisheng_langchain/gpts/utils.py`, `bisheng_langchain/rag/utils.py`, `bisheng/core/config/settings.py`, `pyproject.toml`

- [ ] **Step 1: Delete the two packages**

```bash
cd src/backend
rm -rf bisheng_langchain/autogen_role bisheng_langchain/chains/autogen
```

- [ ] **Step 2: Remove `AutoGenChain` from `bisheng_langchain/chains/__init__.py`**

Delete the first import line and the `'AutoGenChain',` entry from `__all__`. Resulting file:

```python
from bisheng_langchain.chains.combine_documents.stuff import StuffDocumentsChain
from bisheng_langchain.chains.conversational_retrieval.base import ConversationalRetrievalChain
from bisheng_langchain.chains.retrieval.retrieval_chain import RetrievalChain
from bisheng_langchain.chains.router.multi_rule import MultiRuleChain
from bisheng_langchain.chains.router.rule_router import RuleBasedRouter
from bisheng_langchain.chains.transform import TransformChain
from bisheng_langchain.chains.qa_generation.base import QAGenerationChain
from bisheng_langchain.chains.qa_generation.base_v2 import QAGenerationChainV2

from .loader_output import LoaderOutputChain

__all__ = [
    'StuffDocumentsChain', 'LoaderOutputChain', 'RuleBasedRouter',
    'MultiRuleChain', 'RetrievalChain', 'ConversationalRetrievalChain', 'TransformChain',
    'QAGenerationChain', 'QAGenerationChainV2'
]
```

- [ ] **Step 3: Remove the `import_autogenRoles` function from `bisheng_langchain/gpts/utils.py` and `bisheng_langchain/rag/utils.py`**

In each file delete this function:

```python
def import_autogenRoles(autogen: str) -> Any:
    return import_module(f'from bisheng_langchain.autogen_role import {autogen}')
```

- [ ] **Step 4: Remove the unused `autogen_roles` config in `bisheng/core/config/settings.py`**

Delete the line:

```python
    autogen_roles: dict = {}
```

- [ ] **Step 5: Remove the dependency from `pyproject.toml`**

Delete the line `    "bisheng_pyautogen==0.3.2",` from `[project].dependencies`.

- [ ] **Step 6: Verify no autogen references remain**

Run: `grep -rn "autogen_role\|bisheng_pyautogen\|AutoGenChain\|import_autogenRoles\|autogen_roles" bisheng bisheng_langchain --include="*.py"`
Expected: no output (the only acceptable remaining hits are inside `langchain_compat.py`, which is deleted in Part 3).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove dead bisheng_pyautogen (autogen) code and dependency"
```

---

## Part 2 — Evaluation DDD module

### Task 2: Scaffold the module package

**Files:**
- Create: `bisheng/evaluation/__init__.py`, `bisheng/evaluation/api/__init__.py`, `bisheng/evaluation/api/endpoints/__init__.py`, `bisheng/evaluation/domain/__init__.py`, `bisheng/evaluation/domain/models/__init__.py`, `bisheng/evaluation/domain/schemas/__init__.py`, `bisheng/evaluation/domain/repositories/__init__.py`, `bisheng/evaluation/domain/services/__init__.py`

- [ ] **Step 1: Create empty package files**

```bash
cd src/backend
mkdir -p bisheng/evaluation/api/endpoints bisheng/evaluation/domain/{models,schemas,repositories,services}
for d in evaluation evaluation/api evaluation/api/endpoints evaluation/domain evaluation/domain/models evaluation/domain/schemas evaluation/domain/repositories evaluation/domain/services; do
  touch "bisheng/$d/__init__.py"
done
```

- [ ] **Step 2: Commit**

```bash
git add bisheng/evaluation
git commit -m "chore: scaffold evaluation DDD module package"
```

### Task 3: Move the table model into `domain/models/`

**Files:**
- Create: `bisheng/evaluation/domain/models/evaluation.py`

- [ ] **Step 1: Create the model file** (table + enums only; DAO becomes the repository in Task 5)

```python
from datetime import datetime
from enum import Enum
from typing import Dict, Optional

from sqlalchemy import Column, DateTime, Integer, Text, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT


class ExecType(Enum):
    FLOW = 'flow'
    ASSISTANT = 'assistant'
    WORKFLOW = 'workflow'


class EvaluationTaskStatus(Enum):
    running = 1
    failed = 2
    success = 3


class EvaluationBase(SQLModelSerializable):
    user_id: int = Field(default=None, index=True)
    file_name: str = Field(default='', description='Uploaded filename')
    file_path: str = Field(default='', description='Doc. minio address')
    exec_type: str = Field(description='Execute subject categories: assistant/workflow/flow')
    unique_id: str = Field(index=True, description='Unique id of the executing entity')
    version: Optional[int] = Field(default=None, description='Version of workflow or skill id')
    status: int = Field(index=True, default=1,
                        description='Task status: 1 running 2 failed 3 success')
    prompt: str = Field(default='', sa_column=Column(Text), description='Evaluation instruction text')
    result_file_path: str = Field(default='', description='Assessment result minio address')
    result_score: Optional[Dict | str] = Field(default=None, sa_column=Column(JsonType),
                                                description='Final assessment score')
    description: str = Field(default='', sa_column=Column(Text), description='Error description')
    is_delete: int = Field(default=0, description='whether delete')
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))


class Evaluation(EvaluationBase, table=True):
    __tablename__ = 'evaluation'
    id: int = Field(default=None, primary_key=True, unique=True)
```

NOTE: `__tablename__ = 'evaluation'` is set explicitly so the table name is identical to the old model (SQLModel default lowercases the class name to `evaluation`, but pin it to be safe — no Alembic migration is needed).

- [ ] **Step 2: Verify the table name matches the old one**

Run: `cd src/backend && uv run python -c "from bisheng.evaluation.domain.models.evaluation import Evaluation; print(Evaluation.__tablename__)"`
Expected: `evaluation`

- [ ] **Step 3: Commit**

```bash
git add bisheng/evaluation/domain/models/evaluation.py
git commit -m "feat(evaluation): add Evaluation table model in domain/models"
```

### Task 4: Add DTO schemas in `domain/schemas/`

**Files:**
- Create: `bisheng/evaluation/domain/schemas/evaluation.py`

- [ ] **Step 1: Create schemas** (re-export base + read/create DTOs)

```python
from typing import Optional

from bisheng.evaluation.domain.models.evaluation import EvaluationBase


class EvaluationRead(EvaluationBase):
    id: int
    user_name: Optional[str] = None


class EvaluationCreate(EvaluationBase):
    pass
```

- [ ] **Step 2: Commit**

```bash
git add bisheng/evaluation/domain/schemas/evaluation.py
git commit -m "feat(evaluation): add evaluation DTO schemas"
```

### Task 5: Add the repository (replaces `EvaluationDao`)

**Files:**
- Create: `bisheng/evaluation/domain/repositories/evaluation_repository.py`
- Test: `test/evaluation/test_evaluation_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# test/evaluation/test_evaluation_repository.py
from bisheng.evaluation.domain.models.evaluation import Evaluation, ExecType
from bisheng.evaluation.domain.repositories.evaluation_repository import EvaluationRepository


def _make(session, user_id=1, exec_type=ExecType.ASSISTANT.value):
    ev = Evaluation(user_id=user_id, unique_id='u1', exec_type=exec_type)
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def test_get_one_and_update(sqlite_session_patch):
    ev = _make(sqlite_session_patch)
    fetched = EvaluationRepository.get_one_evaluation(ev.id)
    assert fetched is not None and fetched.id == ev.id
    fetched.status = 3
    EvaluationRepository.update_evaluation(fetched)
    assert EvaluationRepository.get_one_evaluation(ev.id).status == 3


def test_list_excludes_flow_and_deleted(sqlite_session_patch):
    _make(sqlite_session_patch, exec_type=ExecType.ASSISTANT.value)
    _make(sqlite_session_patch, exec_type=ExecType.FLOW.value)
    rows, total = EvaluationRepository.get_my_evaluations(user_id=1, page=1, limit=10)
    assert total == 1 and all(r.exec_type != ExecType.FLOW.value for r in rows)
```

NOTE: `sqlite_session_patch` must be a fixture that points `get_sync_db_session` at an in-memory sqlite engine with the `evaluation` table created. Check `test/conftest.py` for an existing equivalent (e.g. a session/engine fixture) and reuse it; if none exists, add a fixture in `test/evaluation/conftest.py` that creates `SQLModel.metadata` tables on an `aiosqlite`/sqlite engine and monkeypatches `bisheng.core.database.get_sync_db_session`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest test/evaluation/test_evaluation_repository.py -q`
Expected: FAIL — `ModuleNotFoundError: ... evaluation_repository`

- [ ] **Step 3: Implement the repository**

```python
# bisheng/evaluation/domain/repositories/evaluation_repository.py
from typing import List

from sqlalchemy import and_, func
from sqlmodel import select

from bisheng.core.database import get_sync_db_session
from bisheng.evaluation.domain.models.evaluation import Evaluation, ExecType


class EvaluationRepository:
    @classmethod
    def get_my_evaluations(cls, user_id: int, page: int, limit: int) -> tuple[List[Evaluation], int]:
        with get_sync_db_session() as session:
            statement = select(Evaluation).where(
                Evaluation.is_delete == 0, Evaluation.user_id == user_id,
                Evaluation.exec_type != ExecType.FLOW.value)
            count_statement = session.query(func.count(Evaluation.id)).where(
                Evaluation.is_delete == 0, Evaluation.user_id == user_id,
                Evaluation.exec_type != ExecType.FLOW.value)
            statement = statement.offset((page - 1) * limit).limit(limit).order_by(
                Evaluation.update_time.desc())
            return session.exec(statement).all(), session.exec(count_statement).scalar()

    @classmethod
    def delete_evaluation(cls, data: Evaluation) -> Evaluation:
        with get_sync_db_session() as session:
            data.is_delete = 1
            session.add(data)
            session.commit()
            return data

    @classmethod
    def get_user_one_evaluation(cls, user_id: int, evaluation_id: int) -> Evaluation:
        with get_sync_db_session() as session:
            statement = select(Evaluation).where(
                and_(Evaluation.id == evaluation_id, Evaluation.user_id == user_id))
            return session.exec(statement).first()

    @classmethod
    def get_one_evaluation(cls, evaluation_id: int) -> Evaluation:
        with get_sync_db_session() as session:
            return session.exec(select(Evaluation).where(Evaluation.id == evaluation_id)).first()

    @classmethod
    def update_evaluation(cls, evaluation: Evaluation) -> Evaluation:
        with get_sync_db_session() as session:
            session.add(evaluation)
            session.commit()
            session.refresh(evaluation)
            return evaluation
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest test/evaluation/test_evaluation_repository.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add bisheng/evaluation/domain/repositories/evaluation_repository.py test/evaluation
git commit -m "feat(evaluation): add EvaluationRepository with tests"
```

### Task 6: Implement the LangChain answer-correctness metric (replaces ragas)

**Files:**
- Create: `bisheng/evaluation/domain/services/answer_correctness.py`
- Test: `test/evaluation/test_answer_correctness.py`

- [ ] **Step 1: Write the failing test**

```python
# test/evaluation/test_answer_correctness.py
import json
import math

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from bisheng.evaluation.domain.services.answer_correctness import compute_answer_correctness


class _StubLLM:
    """Minimal stand-in exposing .generate() like a langchain chat model."""

    def __init__(self, payload_text: str):
        self._text = payload_text

    def generate(self, messages, **kwargs):
        gens = [[ChatGeneration(message=AIMessage(content=self._text))] for _ in messages]
        return LLMResult(generations=gens)


def test_scores_match_formula():
    payload = json.dumps([{
        "statements that are present in both the answer and the ground truth": ["a", "b"],
        "statements present in the answer but not found in the ground truth": ["c"],
        "relevant statements found in the ground truth but omitted in the answer": [],
    }])
    result = compute_answer_correctness(
        _StubLLM(payload), question=["q"], answer=["x"], ground_truths=[["g"]], human_prompt="")
    # tp=2, fp=1, fn=0 -> f1 = 2/(2+0.5*1)=0.8 ; precision=2/3 ; recall=1.0
    assert result["statements_num_overlap"][0] == 2
    assert result["statements_num_answer_only"][0] == 1
    assert result["statements_num_gt_only"][0] == 0
    assert math.isclose(result["answer_f1"][0], 0.8)
    assert math.isclose(result["answer_precision"][0], 2 / 3)
    assert result["answer_recall"][0] == 1.0
    assert result["question"] == ["q"]
    assert result["ground_truths"] == [["g"]]


def test_unparseable_output_yields_nan():
    result = compute_answer_correctness(
        _StubLLM("not json at all"), question=["q"], answer=["x"], ground_truths=[["g"]], human_prompt="")
    assert math.isnan(result["answer_f1"][0])
    assert result["statements_overlap"][0] == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest test/evaluation/test_answer_correctness.py -q`
Expected: FAIL — `ModuleNotFoundError: ... answer_correctness`

- [ ] **Step 3: Implement the metric**

> **Prompt fidelity (do this first):** `bisheng-ragas` is still installed at this point (removed in Task 10). Copy `CORRECTNESS_PROMPT` **verbatim** from `.venv/lib/python3.10/site-packages/bisheng_ragas/metrics/_answer_correctness_bisheng.py` (lines 18–87) — all five few-shot examples, with the literal JSON braces doubled (`{{` / `}}`) and the three real variables kept as single braces `{question}`, `{answer}`, `{ground_truth}`. The block below is **abbreviated** (three of five examples) for readability; the installed file is authoritative for byte-identical output.

```python
# bisheng/evaluation/domain/services/answer_correctness.py
"""LangChain reimplementation of the former bisheng_ragas AnswerCorrectnessBisheng metric.

Output is byte-identical to the previous ragas-based implementation: the same nine
fields, the same f1/precision/recall formulas, and the same default few-shot prompt.
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
from json_repair import repair_json
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate

CORRECTNESS_PROMPT = HumanMessagePromptTemplate.from_template(
    """
Extract following from given question and ground truth

Question:What powers the sun and what is its primary function?
Answer: The sun is powered by nuclear fission, similar to nuclear reactors on Earth, and its primary function is to provide light to the solar system.
Ground truth: The sun is actually powered by nuclear fusion, not fission. In its core, hydrogen atoms fuse to form helium, releasing a tremendous amount of energy. This energy is what lights up the sun and provides heat and light, essential for life on Earth. The sun's light also plays a critical role in Earth's climate system and helps to drive the weather and ocean currents.
Extracted statements:
[
{{
  "statements that are present in both the answer and the ground truth": ["The sun's primary function is to provide light"],
  "statements present in the answer but not found in the ground truth": ["The sun is powered by nuclear fission", "similar to nuclear reactors on Earth"],
  "relevant statements found in the ground truth but omitted in the answer": ["The sun is powered by nuclear fusion, not fission", "In its core, hydrogen atoms fuse to form helium, releasing a tremendous amount of energy", "This energy provides heat and light, essential for life on Earth", "The sun's light plays a critical role in Earth's climate system", "The sun helps to drive the weather and ocean currents"]
}}
]

Question: What is the boiling point of water?
Answer: The boiling point of water is 100 degrees Celsius at sea level.
Ground truth: The boiling point of water is 100 degrees Celsius (212 degrees Fahrenheit) at sea level, but it can change with altitude.
Extracted statements:
[
  {{
    "statements that are present in both the answer and the ground truth": ["The boiling point of water is 100 degrees Celsius at sea level"],
    "statements present in the answer but not found in the ground truth": [],
    "relevant statements found in the ground truth but omitted in the answer": ["The boiling point can change with altitude", "The boiling point of water is 212 degrees Fahrenheit at sea level"]
  }}
]

Question: 公司2021年的研发费用占营业收入的比例是多少？
Answer: 根据提供的信息，公司2021年的研发费用占营业收入的比例为15.86%。
Ground truth: 根据公司招股书披露数据，公司2021年的研发费用占营业收入的比例为15.86%。
Extracted statements:
[
  {{
    "statements that are present in both the answer and the ground truth": ["公司2021年的研发费用占营业收入的比例为15.86%"],
    "statements present in the answer but not found in the ground truth": [],
    "relevant statements found in the ground truth but omitted in the answer": []
  }}
]

Question:{question}
Answer: {answer}
Ground truth: {ground_truth}
Extracted statements:"""  # noqa: E501
)

_KEY_MAP = {
    "TP": "statements that are present in both the answer and the ground truth",
    "FP": "statements present in the answer but not found in the ground truth",
    "FN": "relevant statements found in the ground truth but omitted in the answer",
}


def _parse(text: str) -> list:
    try:
        obj = json.loads(repair_json(text))
    except Exception:
        return []
    return obj if isinstance(obj, list) and obj else []


def compute_answer_correctness(
    llm: BaseChatModel,
    question: list[str],
    answer: list[str],
    ground_truths: list[list[str]],
    human_prompt: str = "",
) -> dict[str, list[Any]]:
    """Return a dict-of-lists with question/answer/ground_truths plus the nine metric fields."""
    prompt_template = (
        HumanMessagePromptTemplate.from_template(human_prompt) if human_prompt else CORRECTNESS_PROMPT
    )
    message_batches = []
    for q, a, g in zip(question, answer, ground_truths):
        msg = prompt_template.format(question=q, ground_truth=g[0], answer=a)
        message_batches.append(ChatPromptTemplate.from_messages([msg]).format_messages())

    llm_result = llm.generate(message_batches)

    out: dict[str, list[Any]] = {
        "question": list(question),
        "answer": list(answer),
        "ground_truths": list(ground_truths),
        "statements_gt_only": [], "statements_num_gt_only": [],
        "statements_answer_only": [], "statements_num_answer_only": [],
        "statements_overlap": [], "statements_num_overlap": [],
        "answer_f1": [], "answer_precision": [], "answer_recall": [],
    }

    for generations in llm_result.generations:
        prediction = _parse(generations[0].text)
        if prediction:
            item = prediction[0]
            overlap = item.get(_KEY_MAP["TP"], "")
            answer_only = item.get(_KEY_MAP["FP"], "")
            gt_only = item.get(_KEY_MAP["FN"], "")
            tp, fp, fn = (len(x) if isinstance(x, list) else np.nan for x in (overlap, answer_only, gt_only))
            out["statements_overlap"].append(str(overlap))
            out["statements_answer_only"].append(str(answer_only))
            out["statements_gt_only"].append(str(gt_only))
            out["statements_num_overlap"].append(tp)
            out["statements_num_answer_only"].append(fp)
            out["statements_num_gt_only"].append(fn)
            out["answer_f1"].append(tp / (tp + 0.5 * (fp + fn)))
            out["answer_precision"].append(tp / (tp + fp) if (tp + fp) != 0 else np.nan)
            out["answer_recall"].append(tp / (tp + fn) if (tp + fn) != 0 else np.nan)
        else:
            out["statements_overlap"].append("")
            out["statements_answer_only"].append("")
            out["statements_gt_only"].append("")
            out["statements_num_overlap"].append(np.nan)
            out["statements_num_answer_only"].append(np.nan)
            out["statements_num_gt_only"].append(np.nan)
            out["answer_f1"].append(np.nan)
            out["answer_precision"].append(np.nan)
            out["answer_recall"].append(np.nan)

    return out
```

NOTE on the prompt template: the original ragas template used single braces around `question`/`answer`/`ground_truth` and doubled braces (`{{`) for the literal JSON examples. Because the template above is one f-string-free triple-quoted block fed to `from_template` (langchain f-string format), every literal brace in the JSON examples is already doubled and the three real variables are written as `{{question}}` → keep them as the **single-brace** `{question}`, `{answer}`, `{ground_truth}` placeholders that langchain interpolates. Verify by Step 4; if langchain raises a KeyError on the JSON braces, ensure all example braces are doubled and the three variables are single-braced (mirror the original file `_answer_correctness_bisheng.py` exactly).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest test/evaluation/test_answer_correctness.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add bisheng/evaluation/domain/services/answer_correctness.py test/evaluation/test_answer_correctness.py
git commit -m "feat(evaluation): reimplement answer-correctness metric in langchain"
```

### Task 7: Move the service into `domain/services/evaluation_service.py`

**Files:**
- Create: `bisheng/evaluation/domain/services/evaluation_service.py` (from `bisheng/api/services/evaluation.py`)

- [ ] **Step 1: Copy the existing service file to the new path**

```bash
cd src/backend
git mv bisheng/api/services/evaluation.py bisheng/evaluation/domain/services/evaluation_service.py
```

- [ ] **Step 2: Replace the ragas imports**

In `evaluation_service.py` delete:

```python
from bisheng_ragas import evaluate
from bisheng_ragas.llms.langchain import LangchainLLM
from bisheng_ragas.metrics import AnswerCorrectnessBisheng
from datasets import Dataset
```

and add:

```python
from bisheng.evaluation.domain.services.answer_correctness import compute_answer_correctness
```

- [ ] **Step 3: Update model/repository imports**

Replace `from bisheng.database.models.evaluation import (Evaluation, EvaluationDao, ExecType, EvaluationTaskStatus)` with:

```python
from bisheng.evaluation.domain.models.evaluation import Evaluation, ExecType, EvaluationTaskStatus
from bisheng.evaluation.domain.repositories.evaluation_repository import EvaluationRepository
from bisheng.evaluation.domain.schemas.evaluation import EvaluationRead
```

Then replace every `EvaluationDao.` call with `EvaluationRepository.` (methods: `get_my_evaluations`, `delete_evaluation`, `get_user_one_evaluation`, `get_one_evaluation`, `update_evaluation`). If `EvaluationRead` was previously imported from the model module, it now comes from schemas (line above).

- [ ] **Step 4: Replace the ragas scoring block**

In `add_evaluation_task`, replace this block (originally `api/services/evaluation.py:288-302`):

```python
        _llm = await LLMService.get_evaluation_llm_object(
            evaluation.user_id, tenant_id=evaluation.tenant_id,
        )
        llm = LangchainLLM(_llm)
        data_samples = {
            "question": [one.get('question') for one in csv_data],
            "answer": [one.get('answer') for one in csv_data],
            "ground_truths": [[one.get('ground_truth')] for one in csv_data]
        }

        dataset = Dataset.from_dict(data_samples)
        answer_correctness_bisheng = AnswerCorrectnessBisheng(llm=llm, human_prompt=evaluation.prompt)
        score = await asyncio.to_thread(evaluate, dataset, [answer_correctness_bisheng])
        df = score.to_pandas()
        result = df.to_dict(orient="list")
```

with:

```python
        _llm = await LLMService.get_evaluation_llm_object(
            evaluation.user_id, tenant_id=evaluation.tenant_id,
        )
        result = await asyncio.to_thread(
            compute_answer_correctness,
            _llm,
            [one.get('question') for one in csv_data],
            [one.get('answer') for one in csv_data],
            [[one.get('ground_truth')] for one in csv_data],
            evaluation.prompt,
        )
```

The downstream `result.get('question')` / `result.get(field)[index]` / total-row / xlsx code stays exactly as is.

- [ ] **Step 5: Verify the service imports cleanly**

Run: `uv run python -c "import bisheng.evaluation.domain.services.evaluation_service as m; print(bool(m.EvaluationService) and bool(m.add_evaluation_task))"`
Expected: `True`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(evaluation): move service to domain layer and drop ragas/datasets usage"
```

### Task 8: Add endpoints + router

**Files:**
- Create: `bisheng/evaluation/api/endpoints/evaluation.py`, `bisheng/evaluation/api/router.py`

- [ ] **Step 1: Create the endpoints file** (from `api/v1/evaluation.py`, with CSV validation no longer using `Dataset`)

```python
# bisheng/evaluation/api/endpoints/evaluation.py
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.server import UploadFileExtError
from bisheng.core.cache.utils import convert_encoding_cchardet
from bisheng.core.database import get_sync_db_session
from bisheng.evaluation.domain.models.evaluation import Evaluation
from bisheng.evaluation.domain.schemas.evaluation import EvaluationCreate
from bisheng.evaluation.domain.services.evaluation_service import EvaluationService, add_evaluation_task
from bisheng.api.v1.schemas import resp_200

router = APIRouter(prefix='/evaluation', tags=['Evaluation'],
                   dependencies=[Depends(UserPayload.get_login_user)])


@router.get('')
def get_evaluation(*,
                   page: Optional[int] = Query(default=1, gt=0, description='Page'),
                   limit: Optional[int] = Query(default=10, gt=0, description='Listings Per Page'),
                   login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get a list of assessment tasks. """
    return EvaluationService.get_evaluation(login_user, page, limit)


@router.post('')
def create_evaluation(*,
                      file: UploadFile,
                      prompt: str = Form(),
                      exec_type: str = Form(),
                      unique_id: str = Form(),
                      version: Optional[int | str] = Form(default=None),
                      background_tasks: BackgroundTasks,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Create Assessment Task. """
    try:
        user_id = login_user.user_id
        if not version:
            version = 0
        try:
            output_file = convert_encoding_cchardet(file.file.read(), 'utf-8')
            csv_data = EvaluationService.parse_csv(file_data=output_file)
            if not csv_data or 'question' not in csv_data[0]:
                raise ValueError('invalid evaluation csv')
        except Exception:
            raise UploadFileExtError()
        finally:
            file.file.seek(0)

        file_name, file_path = EvaluationService.upload_file(file=file)
        db_evaluation = Evaluation.model_validate(EvaluationCreate(
            unique_id=unique_id, exec_type=exec_type, version=version, prompt=prompt,
            user_id=user_id, file_name=file_name, file_path=file_path))
        with get_sync_db_session() as session:
            session.add(db_evaluation)
            session.commit()
            session.refresh(db_evaluation)

        background_tasks.add_task(add_evaluation_task, evaluation_id=db_evaluation.id)
        return resp_200(db_evaluation.copy())
    finally:
        file.file.close()


@router.delete('/{evaluation_id}', status_code=200)
def delete_evaluation(*, evaluation_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Delete Assessment Task (Logical Delete). """
    return EvaluationService.delete_evaluation(evaluation_id, user_payload=login_user)


@router.get('/result/file/download')
async def get_download_url(*, file_url: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get file download address. """
    from bisheng.core.storage.minio.minio_manager import get_minio_storage
    minio_client = await get_minio_storage()
    download_url = await minio_client.get_share_link(file_url)
    return resp_200(data={'url': download_url})


@router.post('/{evaluation_id}/process', status_code=200)
def process_evaluation(*, evaluation_id: int, background_tasks: BackgroundTasks,
                       login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Perform assessment tasks manually. """
    background_tasks.add_task(add_evaluation_task, evaluation_id=evaluation_id)
```

NOTE: confirm `EvaluationService.parse_csv` returns a list of dicts (it does — see the moved service). The old route built a `Dataset` purely to validate; the column-presence check above preserves the "reject bad CSV → `UploadFileExtError`" behavior.

- [ ] **Step 2: Create the module router aggregator**

```python
# bisheng/evaluation/api/router.py
from fastapi import APIRouter

from bisheng.evaluation.api.endpoints.evaluation import router as evaluation_router

router = APIRouter()
router.include_router(evaluation_router)
```

- [ ] **Step 3: Verify the endpoints import**

Run: `uv run python -c "from bisheng.evaluation.api.router import router; print(len(router.routes))"`
Expected: `5`

- [ ] **Step 4: Commit**

```bash
git add bisheng/evaluation/api
git commit -m "feat(evaluation): add api endpoints and module router"
```

### Task 9: Wire the router, update tenant filter, delete old files

**Files:**
- Modify: `bisheng/api/router.py`, `bisheng/api/v1/__init__.py`, `bisheng/core/database/tenant_filter.py`
- Delete: `bisheng/api/v1/evaluation.py`, `bisheng/database/models/evaluation.py`

- [ ] **Step 1: Register the new router in `bisheng/api/router.py`**

Find how other DDD modules register (e.g. `from bisheng.knowledge.api.router import router as knowledge_router` then `router.include_router(...)`). Add the same for evaluation:

```python
from bisheng.evaluation.api.router import router as evaluation_router
# ... alongside the other include_router(...) calls:
router.include_router(evaluation_router)
```

- [ ] **Step 2: Remove the old route registration from `bisheng/api/v1/__init__.py`**

Delete the `evaluation` import and its `include_router`/list entry (mirror how the other v1 routers are removed — grep `evaluation` in that file and remove only those lines).

- [ ] **Step 3: Update the tenant-aware module path in `bisheng/core/database/tenant_filter.py`**

Replace `'bisheng.database.models.evaluation',` with `'bisheng.evaluation.domain.models.evaluation',` in `_TENANT_AWARE_MODEL_MODULES`.

- [ ] **Step 4: Delete the old route and model files**

```bash
cd src/backend
rm bisheng/api/v1/evaluation.py bisheng/database/models/evaluation.py
```

- [ ] **Step 5: Verify no stale imports of the old paths remain**

Run: `grep -rn "api.services.evaluation\|api.v1.evaluation\|database.models.evaluation" bisheng --include="*.py"`
Expected: no output

- [ ] **Step 6: Verify the table is still discovered as tenant-aware**

Run:
```bash
uv run python -c "
from bisheng.core.database import tenant_filter as tf
tf._force_import_all_models()
tables = tf._discover_tenant_aware_tables()
print('evaluation tenant-aware:', 'evaluation' in tables)
"
```
Expected: `evaluation tenant-aware: True`

- [ ] **Step 7: Verify the app boots**

Run: `uv run python -c "import bisheng.main; print('boot OK')"`
Expected: `boot OK` (ignore the transformers/jieba warnings)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(evaluation): wire DDD router, fix tenant module path, remove old route/model"
```

---

## Part 3 — Drop dependencies and delete the shim

### Task 10: Remove ragas/datasets and the compat shim

**Files:**
- Delete: `bisheng_langchain/rag/scoring/ragas_score.py`, `bisheng_langchain/langchain_compat.py`
- Modify: `bisheng/__init__.py`, `bisheng_langchain/__init__.py`, `pyproject.toml`

- [ ] **Step 1: Delete the dead benchmark script and the shim**

```bash
cd src/backend
rm bisheng_langchain/rag/scoring/ragas_score.py bisheng_langchain/langchain_compat.py
```

- [ ] **Step 2: Remove the shim import from `bisheng/__init__.py`**

Delete these two lines:

```python
# Install the LangChain 1.x compatibility shim before any dependency that still
# imports legacy ``langchain.*`` paths (bisheng_pyautogen / bisheng_ragas) loads.
from bisheng_langchain import langchain_compat as _langchain_compat  # noqa: F401
```

- [ ] **Step 3: Reset `bisheng_langchain/__init__.py` to empty**

```bash
: > bisheng_langchain/__init__.py
```

- [ ] **Step 4: Remove the dependencies from `pyproject.toml`**

Delete the lines `    "bisheng-ragas>=1.0.3",` and `    "datasets>=4.3.0",` from `[project].dependencies`.

- [ ] **Step 5: Re-lock and sync**

Run: `uv lock && uv sync`
Expected: lock succeeds; `bisheng-ragas`, `datasets`, `bisheng-pyautogen` removed from `uv.lock`.

- [ ] **Step 6: Verify the packages are gone and nothing imports them**

Run: `grep -rn "bisheng_ragas\|from datasets\|import datasets\|langchain_compat" bisheng bisheng_langchain --include="*.py"`
Expected: no output
Run: `grep -c "bisheng-ragas\|bisheng_pyautogen\|^name = \"datasets\"" uv.lock`
Expected: `0`

- [ ] **Step 7: Verify the app still boots without the shim**

Run: `uv run python -c "import bisheng.main; print('boot OK without shim')"`
Expected: `boot OK without shim`

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: drop bisheng-ragas/datasets deps and delete langchain compat shim"
```

### Task 11: Full regression check

- [ ] **Step 1: Run the new evaluation tests**

Run: `uv run pytest test/evaluation/ -q`
Expected: PASS (all tests from Tasks 5 and 6)

- [ ] **Step 2: Run the full non-e2e suite and confirm no new regressions**

Run: `uv run pytest test/ -m "not e2e" -q -p no:cacheprovider --continue-on-collection-errors --tb=no 2>&1 | tail -1`
Expected: `2219 passed` (± unchanged from the pre-refactor baseline; the 320 pre-existing infra failures are unrelated). If the passed count drops, investigate the delta before proceeding.

- [ ] **Step 3: Lint the changed files**

Run: `uv run ruff check --fix bisheng/evaluation bisheng_langchain/chains/__init__.py bisheng/__init__.py`
Expected: no remaining errors in the new module (pre-existing E501 etc. elsewhere are acceptable).

- [ ] **Step 4: Final commit (if ruff changed anything)**

```bash
git add -A
git commit -m "style: ruff fixes for evaluation module" || echo "nothing to commit"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** Part 1 = autogen removal (Task 1). Part 2 = full DDD module (Tasks 2–9): models, schemas, repository, langchain metric, service, endpoints, router, tenant-filter path, deletes. Part 3 = drop ragas/datasets + shim (Task 10) + regression (Task 11). All three spec decisions covered.
- **No DB migration:** `__tablename__='evaluation'` is pinned (Task 3) so the schema is unchanged.
- **Tenant gotcha:** Task 9 Step 3 + the Step 6 assertion guard the silent-leak risk.
- **Type consistency:** `EvaluationRepository` method names match the calls substituted in Task 7; `compute_answer_correctness` signature in Task 6 matches the call in Task 7 Step 4; the result dict keys match the downstream `result.get(field)` reads in the moved service.
- **Prompt fidelity:** if langchain's f-string template chokes on the JSON example braces, mirror `_answer_correctness_bisheng.py` brace-doubling exactly (Task 6 NOTE).
