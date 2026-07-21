from __future__ import annotations

import inspect
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from kombu.exceptions import OperationalError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode import portal_course as errors
from bisheng.shougang_portal_course.api import router as course_router_module
from bisheng.shougang_portal_course.api.endpoints import admin, catalog, learning
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CourseUpdate,
    ProgressRead,
    ProgressUpdate,
    VideoUpdate,
)


def test_portal_course_error_codes_are_stable_and_unique():
    classes = [
        errors.PortalCourseNotFoundError,
        errors.PortalCourseVideoNotFoundError,
        errors.PortalCourseNotPublishableError,
        errors.PortalCourseMediaTooLargeError,
        errors.PortalCourseMediaUnsupportedError,
        errors.PortalCourseUrlInvalidError,
        errors.PortalCourseSourceInvalidError,
        errors.PortalCourseProbeFailedError,
        errors.PortalCourseSourceReplaceError,
    ]
    assert [item.Code for item in classes] == list(range(25001, 25010))
    assert len({item.Code for item in classes}) == 9


def test_course_router_exposes_catalog_admin_and_learning_resources():
    routes = {
        (method, route.path)
        for route in course_router_module.router.routes
        for method in route.methods
    }
    expected = {
        ("GET", "/shougang-portal/course-catalog/courses"),
        ("GET", "/shougang-portal/course-catalog/courses/{course_id}"),
        ("GET", "/shougang-portal/course-admin/courses"),
        ("POST", "/shougang-portal/course-admin/courses"),
        ("POST", "/shougang-portal/course-admin/courses/{course_id}/videos/upload"),
        ("POST", "/shougang-portal/course-admin/courses/{course_id}/videos/url"),
        ("GET", "/shougang-portal/course-learning/courses/{course_id}/progress"),
        ("PUT", "/shougang-portal/course-learning/videos/{video_id}/progress"),
    }
    assert expected <= routes


def test_route_groups_use_the_expected_authentication_dependencies():
    catalog_source = inspect.getsource(catalog)
    admin_source = inspect.getsource(admin)
    learning_source = inspect.getsource(learning)

    assert "Depends(UserPayload.get_login_user)" in catalog_source
    assert "Depends(UserPayload.get_admin_user)" in admin_source
    assert "Depends(UserPayload.get_login_user)" in learning_source
    assert "_MAX_PROGRESS_WRITE_ATTEMPTS = 2" in learning_source
    assert "except IntegrityError" in learning_source


def test_video_delete_reads_and_writes_inside_one_transaction():
    source = inspect.getsource(admin.delete_video)
    transaction_position = source.index("async with session.begin()")
    lookup_position = source.index("repository.get_video")

    assert transaction_position < lookup_position


def test_progress_body_rejects_forged_identity_fields():
    with pytest.raises(ValidationError):
        ProgressUpdate.model_validate(
            {
                "progress_seconds": 10,
                "completed": False,
                "user_id": 99,
                "tenant_id": 88,
            }
        )


@pytest.mark.parametrize(
    ("schema", "field"),
    [
        pytest.param(CourseUpdate, "name", id="course-name"),
        pytest.param(CourseUpdate, "tags", id="course-tags"),
        pytest.param(CourseUpdate, "instructor", id="course-instructor"),
        pytest.param(CourseUpdate, "organization", id="course-organization"),
        pytest.param(CourseUpdate, "description", id="course-description"),
        pytest.param(CourseUpdate, "enabled", id="course-enabled"),
        pytest.param(CourseUpdate, "show_on_home", id="course-show-on-home"),
        pytest.param(CourseUpdate, "sort_order", id="course-sort-order"),
        pytest.param(VideoUpdate, "title", id="video-title"),
        pytest.param(VideoUpdate, "duration_seconds", id="video-duration"),
        pytest.param(VideoUpdate, "enabled", id="video-enabled"),
        pytest.param(VideoUpdate, "sort_order", id="video-sort-order"),
    ],
)
def test_update_schemas_reject_explicit_null_but_allow_omitted_fields(schema, field):
    assert schema.model_validate({}).model_fields_set == set()

    with pytest.raises(ValidationError):
        schema.model_validate({field: None})


@pytest.mark.parametrize(
    "enqueue_error",
    [
        pytest.param(OperationalError("broker unavailable"), id="kombu-operational"),
        pytest.param(OSError("transport unavailable"), id="os-error"),
    ],
)
def test_cleanup_enqueue_broker_failure_is_best_effort(monkeypatch, enqueue_error):
    def fail_enqueue(_job_ids, _tenant_id):
        raise enqueue_error

    cleanup_tasks = ModuleType("bisheng.worker.portal_course.tasks")
    cleanup_tasks.enqueue_portal_course_cleanup = fail_enqueue
    cleanup_package = ModuleType("bisheng.worker.portal_course")
    cleanup_package.__path__ = []
    cleanup_package.tasks = cleanup_tasks
    monkeypatch.setitem(sys.modules, cleanup_package.__name__, cleanup_package)
    monkeypatch.setitem(sys.modules, cleanup_tasks.__name__, cleanup_tasks)

    warning = Mock()
    monkeypatch.setattr(
        admin,
        "logger",
        SimpleNamespace(warning=warning),
        raising=False,
    )

    admin._enqueue_cleanup(["j" * 32], 7)

    warning.assert_called_once_with(
        "portal course media cleanup enqueue failed tenant_id=%s job_ids=%s "
        "error_type=%s; recovery scan will retry",
        7,
        ["j" * 32],
        type(enqueue_error).__name__,
        exc_info=True,
    )


def test_cleanup_enqueue_does_not_hide_programming_errors(monkeypatch):
    def fail_enqueue(_job_ids, _tenant_id):
        raise RuntimeError("programming error")

    cleanup_tasks = ModuleType("bisheng.worker.portal_course.tasks")
    cleanup_tasks.enqueue_portal_course_cleanup = fail_enqueue
    cleanup_package = ModuleType("bisheng.worker.portal_course")
    cleanup_package.__path__ = []
    cleanup_package.tasks = cleanup_tasks
    monkeypatch.setitem(sys.modules, cleanup_package.__name__, cleanup_package)
    monkeypatch.setitem(sys.modules, cleanup_tasks.__name__, cleanup_tasks)

    with pytest.raises(RuntimeError, match="programming error"):
        admin._enqueue_cleanup(["j" * 32], 7)


async def test_progress_endpoint_retries_a_concurrent_first_insert(monkeypatch):
    attempts = 0
    reports = 0

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            return False

    class Session:
        def begin(self):
            return Transaction()

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class ProgressService:
        def __init__(self, session):
            del session

        async def report(self, **kwargs):
            nonlocal reports
            reports += 1
            return ProgressRead(
                video_id=kwargs["video_id"],
                progress_seconds=12,
                completed=False,
            )

    monkeypatch.setattr(learning, "get_async_db_session", SessionContext)
    monkeypatch.setattr(learning, "PortalCourseProgressService", ProgressService)
    monkeypatch.setattr(learning, "_tenant_id", lambda _user: 1)
    warning = Mock()
    monkeypatch.setattr(learning.logger, "warning", warning)

    response = await learning.report_video_progress(
        "v" * 32,
        ProgressUpdate(progress_seconds=12, completed=False),
        SimpleNamespace(user_id=9, tenant_id=1),
    )

    assert response.data["video_id"] == "v" * 32
    assert attempts == 2
    assert reports == 2
    warning.assert_called_once_with(
        "portal course progress write conflict tenant_id=%s user_id=%s "
        "video_id=%s attempt=%s",
        1,
        9,
        "v" * 32,
        1,
    )
