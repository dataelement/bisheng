from typing import Optional

from bisheng.evaluation.domain.models.evaluation import EvaluationBase


class EvaluationRead(EvaluationBase):
    id: int
    user_name: Optional[str] = None


class EvaluationCreate(EvaluationBase):
    pass
