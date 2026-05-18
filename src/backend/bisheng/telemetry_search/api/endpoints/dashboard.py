from typing import List

from fastapi import APIRouter, Request, Depends, Body, Query

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData
from bisheng.telemetry_search.domain.models.dashboard import DashboardStatus, DashboardComponent
from bisheng.telemetry_search.domain.schemas.dashboard import DashboardCreate, DashboardRead
from bisheng.telemetry_search.domain.services.component import TimeFilter
from bisheng.telemetry_search.domain.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["TelemetryDashboard"])


@router.get("", summary="Get all dashboards")
async def get_all_dashboards(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                             keyword: str = None):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.get_dashboards(keyword=keyword)
    return resp_200(data=PageData(data=res, total=len(res)))


@router.get("/{dashboard_id}", summary="Get a dashboard detail")
async def get_dashboard_detail(request: Request, dashboard_id: int, from_share: bool = False,
                               login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.get_dashboard_detail(dashboard_id, from_share)
    return resp_200(data=res)


@router.post("", summary="Create a new dashboard")
async def create_dashboard(request: Request, data: DashboardCreate,
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.create_dashboard(data)
    return resp_200(data=res)


@router.delete("/{dashboard_id}", summary="Delete a dashboard")
async def delete_dashboard(request: Request, dashboard_id: int,
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    await dashboard_service.delete_dashboard(dashboard_id)
    return resp_200()


@router.put("/{dashboard_id}", summary="Update a dashboard detail")
async def update_dashboard(request: Request, dashboard_id: int, data: DashboardRead,
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    data.id = dashboard_id
    res = await dashboard_service.update_dashboard(data)
    return resp_200(data=res)


@router.post("/{dashboard_id}/title", summary="Update a dashboard title")
async def update_dashboard_title(request: Request, dashboard_id: int, title: str = Body(..., embed=True),
                                 login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.update_dashboard_title(dashboard_id, title)
    return resp_200(data=res)


@router.post("/{dashboard_id}/status", summary="Update a dashboard status")
async def update_dashboard_status(request: Request, dashboard_id: int, status: DashboardStatus = Body(..., embed=True),
                                  login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.update_dashboard_status(dashboard_id, status)
    return resp_200(data=res)


@router.post("/{dashboard_id}/default", summary="set dashboard default")
async def set_default_dashboard(request: Request, dashboard_id: int,
                                login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.set_default_dashboard(dashboard_id)
    return resp_200(data=res)


@router.post("/{dashboard_id}/copy", summary="copy dashboard")
async def copy_dashboard(request: Request, dashboard_id: int, new_title: str = Body("Unnamed Dashboard", embed=True),
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.copy_dashboard(dashboard_id, new_title)
    return resp_200(data=res)


@router.post("/component/query", summary="query dashboard components data")
async def query_component_data(request: Request,
                               dashboard_id: int = Body(..., embed=True),
                               component_id: str = Body(None, embed=True),
                               component_data: DashboardComponent = Body(None, embed=True),
                               time_filters: List[TimeFilter] = Body(None, embed=True),
                               login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.query_component_data(dashboard_id, component_id, component_data, time_filters)
    return resp_200(data=res)


@router.get("/dataset/list", summary="Get all available datasets for dashboards")
async def get_available_datasets(
):
    datasets = await DashboardService.get_dataset_options()

    return resp_200(data=datasets)


# Field Enumeration Acquisition
@router.get("/dataset/field/enums", summary="Get all available fields for a dataset")
async def get_dataset_field_enums(
        index_name: str = Query(..., description="The index name of the dataset"),
        field: str = Query(..., description="The field name of the dataset"),
        keyword: str = Query(None, description="The keyword to filter field enums"),
        size: int = Query(default=20, description="The size of the dataset"),
        page: int = Query(default=1, description="The page number of the dataset")
):
    """
    Get all available fields for a dataset
    Args:
        keyword:
        page:
        size:
        index_name:
        field:

    Returns:
    """

    field_enums = await DashboardService.get_dataset_field_enums(index_name, field, keyword, size, page)
    return resp_200(data=field_enums)
