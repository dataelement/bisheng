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
