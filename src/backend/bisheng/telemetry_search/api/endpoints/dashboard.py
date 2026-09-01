from typing import Any, List

from fastapi import APIRouter, Request, Depends, Body, Query

from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData
from bisheng.telemetry_search.domain.models.dashboard import DashboardStatus, DashboardComponent
from bisheng.telemetry_search.domain.schemas.dashboard import DashboardCreate, DashboardRead
from bisheng.telemetry_search.domain.services.component import TimeFilter
from bisheng.telemetry_search.domain.schemas.component import DimensionQueryFilter
from bisheng.telemetry_search.domain.services.dashboard import DashboardService
from bisheng.telemetry_search.domain.services.dashboard_export_service import DashboardExportService

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
                               dimension_filters: List[DimensionQueryFilter] = Body(None, embed=True),
                               login_user: UserPayload = Depends(UserPayload.get_login_user)):
    dashboard_service = DashboardService(request=request, login_user=login_user)
    res = await dashboard_service.query_component_data(
        dashboard_id,
        component_id,
        component_data,
        time_filters,
        dimension_filters,
    )
    return resp_200(data=res)


@router.post("/component/{component_id}/export", summary="F058: export one drill-down category as Excel")
async def export_component_detail(request: Request,
                                  component_id: str,
                                  dashboard_id: int = Body(..., embed=True),
                                  dimension_field: str = Body(..., embed=True),
                                  dimension_value: Any = Body(..., embed=True),
                                  time_filters: List[TimeFilter] = Body(None, embed=True),
                                  dimension_filters: List[DimensionQueryFilter] = Body(None, embed=True),
                                  login_user: UserPayload = Depends(UserPayload.get_login_user)):
    export_service = DashboardExportService(request=request, login_user=login_user)
    file_url = await export_service.export_component_detail(
        dashboard_id,
        component_id,
        dimension_field,
        dimension_value,
        time_filters,
        dimension_filters,
    )
    return resp_200(data={"file_url": file_url})


@router.post("/component/{component_id}/export-all", summary="F058: export the whole component as multi-sheet Excel")
async def export_component_all(request: Request,
                               component_id: str,
                               dashboard_id: int = Body(..., embed=True),
                               time_filters: List[TimeFilter] = Body(None, embed=True),
                               dimension_filters: List[DimensionQueryFilter] = Body(None, embed=True),
                               login_user: UserPayload = Depends(UserPayload.get_login_user)):
    export_service = DashboardExportService(request=request, login_user=login_user)
    file_url = await export_service.export_component_all(
        dashboard_id,
        component_id,
        time_filters,
        dimension_filters,
    )
    return resp_200(data={"file_url": file_url})


@router.get("/dataset/list", summary="Get all available datasets for dashboards")
async def get_available_datasets(
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    datasets = await DashboardService.get_dataset_options()

    return resp_200(data=datasets)


# Field Enumeration Acquisition
@router.get("/dataset/field/enums", summary="Get all available fields for a dataset")
async def get_dataset_field_enums(
        request: Request,
        index_name: str = Query(..., description="The index name of the dataset"),
        field: str = Query(..., description="The field name of the dataset"),
        label_field: str = Query(None, description="Optional display-label dimension"),
        exact_values: str = Query(None, description="Comma-separated exact values"),
        keyword: str = Query(None, description="The keyword to filter field enums"),
        size: int = Query(default=20, description="The size of the dataset"),
        page: int = Query(default=1, description="The page number of the dataset"),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
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

    dashboard_service = DashboardService(request=request, login_user=login_user)
    field_enums = await dashboard_service.get_dataset_field_enums(
        dataset_code=index_name,
        field=field,
        keyword=keyword,
        size=size,
        page=page,
        label_field=label_field,
        exact_values=exact_values,
    )
    return resp_200(data=field_enums)
