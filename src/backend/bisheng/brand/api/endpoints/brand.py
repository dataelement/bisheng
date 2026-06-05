from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import PlainTextResponse

from bisheng.brand.domain.schemas.brand_schema import BrandAssetCategory, BrandConfigUpdate
from bisheng.brand.domain.services.brand_service import BrandService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200


router = APIRouter()


def get_brand_service() -> BrandService:
    return BrandService()


@router.get('/config')
async def get_brand_config(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    service: BrandService = Depends(get_brand_service),
):
    config = await service.get_config()
    return resp_200(config.model_dump(mode='json'))


@router.put('/config')
async def update_brand_config(
    data: BrandConfigUpdate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    service: BrandService = Depends(get_brand_service),
):
    config = await service.save_config(data)
    return resp_200(config.model_dump(mode='json'))


@router.get('/assets/options')
async def list_brand_asset_options(
    category: BrandAssetCategory = Query(...),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    service: BrandService = Depends(get_brand_service),
):
    options = await service.list_asset_options(category)
    return resp_200([option.model_dump(mode='json') for option in options])


@router.post('/assets')
async def upload_brand_asset(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    file: UploadFile = File(...),
    category: BrandAssetCategory | None = Form(default=None),
    service: BrandService = Depends(get_brand_service),
):
    try:
        result = await service.upload_asset(file, category=category)
        return resp_200(result.model_dump(mode='json'))
    finally:
        if file:
            await file.close()


@router.delete('/assets')
async def delete_brand_asset(
    category: BrandAssetCategory = Query(...),
    relative_path: str = Query(...),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
    service: BrandService = Depends(get_brand_service),
):
    default_asset = await service.delete_asset(category, relative_path)
    return resp_200(default_asset.model_dump(mode='json'))


@router.get('/runtime.js')
async def get_brand_runtime_script(
    service: BrandService = Depends(get_brand_service),
):
    script = await service.build_runtime_script()
    return PlainTextResponse(
        script,
        media_type='application/javascript',
        headers={'Cache-Control': 'no-store'},
    )
