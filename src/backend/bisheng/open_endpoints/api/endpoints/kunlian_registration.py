"""仅由本地合同测试装配的 F121 候选接口。"""

from fastapi import APIRouter, Depends, Query

from bisheng.common.errcode.flow import WorkflowRegistrationUnavailable
from bisheng.common.schemas.api import resp_200
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationReceipt

router = APIRouter(prefix="/kunlian", tags=["Kunlian Workflow registration candidate"])


def read_identity():
    # TODO [F121][EXT-01] 正式的代用户身份由确认后的开放平台入口提供。
    raise WorkflowRegistrationUnavailable()


def sync_reader():
    # TODO [F121][EXT-02] 正式同步凭据确认后装配读取权限。
    raise WorkflowRegistrationUnavailable()


def receipt_writer():
    # TODO [F121][EXT-02] 回执是单独授权的写入动作。
    raise WorkflowRegistrationUnavailable()


@router.get("/workflows")
async def workflows(
    name: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    reader=Depends(read_identity),
):
    return resp_200(data=await reader.list(name, cursor, limit))


@router.get("/workflows/{workflow_id}")
async def workflow(workflow_id: str, reader=Depends(read_identity)):
    return resp_200(data=await reader.detail(workflow_id))


@router.get("/workflow-registrations/snapshot")
def snapshot(page_token: str | None = None, limit: int = Query(100, ge=1, le=100), reader=Depends(sync_reader)):
    return resp_200(data=reader.snapshot(page_token, limit))


@router.get("/workflow-registrations/changes")
def changes(
    cursor: str | None = None,
    page_token: str | None = None,
    limit: int = Query(100, ge=1, le=100),
    reader=Depends(sync_reader),
):
    return resp_200(data=reader.changes(cursor=cursor, page_token=page_token, limit=limit))


@router.get("/workflow-registrations/{workflow_id}/versions/{version_id}")
def version(workflow_id: str, version_id: int, reader=Depends(sync_reader)):
    return resp_200(data=reader.version(workflow_id, version_id))


@router.post("/workflow-registrations/receipts")
def receipt(data: RegistrationReceipt, writer=Depends(receipt_writer)):
    return resp_200(data={"applied": writer.receipt(data)})
