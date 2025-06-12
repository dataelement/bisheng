from fastapi import APIRouter, Body, Request
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.api.services.pack_tool_service import PackToolService

router = APIRouter(prefix='/pack', tags=['Pack'])

@router.post('/albl', response_model=UnifiedResponseModel, status_code=200)
def albl_pack(
        prompt: str = Body(..., description="提示词"),
        model: str = Body("wanx-v1", description="模型"),
        size: str = Body("1024*1024", description="尺寸：1024*1024：默认值；20*1280；768*1152；1280*720"),
        n: str = Body(1, description="数量，取值范围为1~4"),
        request: Request = None
):
    """阿里百炼"""
    if size == "":
        size = "1024*1024"
    if model == "":
        model = "wanx-v1"
    if n == "":
        n = 1
    else:
        n = int(n)
    urls = PackToolService.albl_pack(prompt, model, size, n, request)
    return resp_200(data={"urls": urls})

@router.post('/txhy', response_model=UnifiedResponseModel, status_code=200)
def txhy_pack(
        prompt: str = Body(..., description="提示词"),
        size: str = Body("1024:1024", description="尺寸：1024:1024(默认值)、768:768（1:1）、768:1024（3:4）、1024:768（4:3）、1024:1024（1:1）、720:1280（9:16）、1280:720（16:9）、768:1280（3:5）、1280:768（5:3）"),
        n: str = Body("1", description="数量，取值范围为1~4"),
        request: Request = None
):
    """腾讯混元"""
    if size == "":
        size = "1024:1024"
    if n == "":
        n = 1
    else:
        n = int(n)
    urls = PackToolService.txhy_pack(prompt, size.replace("*", ":"), n, request)
    return resp_200(data={"urls": urls})

@router.post('/zjdb', response_model=UnifiedResponseModel, status_code=200)
def zjdb_pack(
        prompt: str = Body(..., description="提示词"),
        model: str = Body("doubao-seedream-3-0-t2i-250415", description="模型ID"),
        size: str = Body("1024x1024", description="尺寸：1024x1024 （1:1）; 864x1152 （3:4）; 1152x864 （4:3）; 1280x720 （16:9）; 720x1280 （9:16）; 832x1248 （2:3）; 1248x832 （3:2）; 1512x648 （21:9）"),
        request: Request = None
):
    """字节豆包"""
    if size == "":
        size = "1024x1024"
    if model == "":
        model = "doubao-seedream-3-0-t2i-250415"
    urls = PackToolService.zjdb_pack(prompt, model, size.replace("*", "x"), request)
    return resp_200(data={"urls": urls})