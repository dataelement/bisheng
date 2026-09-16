"""平台能力接线样例(SDK 版)—— auth / retrieve / storage 三件套齐用。

与同目录的 `../example/`(零依赖、只读头) 是**两条都合法的路径**:那个证明「不装 SDK 也能接线」,
这个是平台推荐的默认写法。三件事的正确做法在这里各只有一行。

四条托管运行契约照旧(见「部署纳管」技能):
* 监听平台注入的 PORT;绑 0.0.0.0,不是 127.0.0.1。
* 只往 /data 写(本样例不落库,附件一律走 storage)。
* 对外链接带 BISHENG_APP_BASE_PATH。

本地跑:`bisheng dev`(它会注入身份头与同名环境变量),然后开它打印的**本地入口地址**——
不是应用自己的端口,直连端口的请求没有身份。
"""

from __future__ import annotations

import os

from bisheng_sdk import auth, errors, retrieve, storage
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

# 读平台注入的端口,取不到用本地默认。别写死。
PORT = int(os.environ.get("PORT") or os.environ.get("BISHENG_APP_PORT") or 8080)

# 对外基路径。平台上是 /apps/{slug},本地是空串。所有对外链接都过 url()。
BASE_PATH = (os.environ.get("BISHENG_APP_BASE_PATH") or "").rstrip("/")

# ⚠️ 与 bisheng-app.yaml 的 capabilities.knowledge_bases 同一份事实:
# 那里声明「这个应用会检索哪些知识库」(审批通过后成为平台侧的白名单),
# 这里是调用时传的 id。**改一处就要改另一处**,否则线上会得到「目标不可及」。
KNOWLEDGE_BASE_IDS = [12]

app = FastAPI(title="平台能力接线样例(SDK 版)")

# 这一行是 auth 的全部接线:它把每个请求的注入头放进上下文,
# auth.current_user() / retrieve / storage 都从那里取。没有它,处处抛「未取得平台注入身份」。
app.add_middleware(auth.ASGIMiddleware)


def url(path: str) -> str:
    """把应用内部路径拼成对外可点的地址(漏一处那处就跳到平台根路径)。"""
    return f"{BASE_PATH}{path}"


def problem(exc: errors.BishengSdkError, status: int = 400) -> JSONResponse:
    """把 SDK 异常翻成一句用户看得懂的话 —— 不是 500,更不是堆栈。

    `next_step` 是 SDK 替每类失败写好的「怎么改」,原样透出去比重写一遍准确。
    """
    return JSONResponse(status_code=status, content={"error": exc.message, "next_step": exc.next_step})


@app.get("/healthz")
def healthz() -> Response:
    """健康探活 —— **刻意不读身份**。

    探活请求不经平台入口、没有身份头,在这里读身份会抛错,
    平台于是把整个应用判成不健康。身份是给业务端点用的,不是给探针用的。
    """
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    """首页:一行拿到当前访问者。"""
    user = auth.current_user()
    badge = "(本地开发 · 服务账号)" if user.subject_kind == "service_account" else ""
    dept = user.dept_name or "无部门"
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>平台能力接线样例</title>"
        f"<h1>你好,{user.user_name} {badge}</h1>"
        f"<p>部门:{dept}</p>"
        f"<p><a href='{url('/files')}'>我的附件</a></p>"
        "<form method='post' enctype='multipart/form-data' action='"
        f"{url('/upload')}'><input type='file' name='file'><button>上传</button></form>"
    )


@app.get("/__whoami")
def whoami(request: Request) -> JSONResponse:
    """回显本请求收到的注入头,供 selfcheck.py 解析。

    只回显平台注入的那一组(`x-bisheng-` 前缀),不回显 Authorization、Cookie 之类。
    真实应用不需要这个端点。
    """
    injected = {k: v for k, v in request.headers.items() if k.lower().startswith("x-bisheng-")}
    return JSONResponse(injected)


@app.post("/ask")
def ask(q: str) -> JSONResponse:
    """以**当前访问者**的身份检索 —— 不是以应用自己的身份。

    平台侧还会再按「应用声明的白名单 ∩ 这个用户的可见范围」过滤一遍,所以
    同一个问题,不同的人问,拿到的片段本来就该不一样。
    """
    try:
        result = retrieve.search(q, knowledge_base_ids=KNOWLEDGE_BASE_IDS, top_k=5)
    except errors.VisitorCredentialMissingError as exc:
        return problem(exc, status=401)
    except errors.VisitorCredentialRejectedError as exc:
        return problem(exc, status=401)
    except errors.AppCredentialMissingError as exc:
        # 应用自己的运行期凭据没注入 —— 环境的问题,不是这次访问者的问题。
        # 单列出来是为了不让它混进下面的 502:那会读成"平台挂了",实际是本应用没拿到凭据。
        return problem(exc, status=503)
    except errors.ScopeMissingError as exc:
        return problem(exc, status=403)
    except errors.CapabilityRevokedError as exc:
        return problem(exc, status=403)
    except errors.CapabilityNotDeclaredError as exc:
        return problem(exc, status=403)
    except errors.TargetUnreachableError as exc:
        return problem(exc, status=400)
    except errors.BishengSdkError as exc:
        # 权限引擎不可用 / 平台不可达 / 版本不兼容都落这里:是失败,不是「没查到」。
        # 绝不把它变成「返回空列表」,那会让越权和故障都看起来像正常结果。
        return problem(exc, status=502)

    return JSONResponse(
        {
            "total": result.total,
            "chunks": [
                {"content": chunk.content, "document": chunk.document_name, "index": chunk.chunk_index}
                for chunk in result.chunks
            ],
        }
    )


@app.post("/upload")
async def upload(file: UploadFile) -> JSONResponse:
    """附件按人分目录存进**本应用的**附件空间。

    路径是应用内相对路径 —— 没有 bucket、没有对象键、没有存储地址,
    也拿不到匿名直链(要给用户下载就像下面 /files/{path} 那样自己吐字节)。
    """
    user = auth.current_user()
    path = f"{user.user_id}/{os.path.basename(file.filename or 'upload.bin')}"
    try:
        meta = storage.put(path, await file.read(), content_type=file.content_type)
    except errors.AttachmentTooLargeError as exc:
        return problem(exc, status=413)
    except errors.InvalidAttachmentPathError as exc:
        return problem(exc, status=400)
    except errors.BishengSdkError as exc:
        return problem(exc, status=502)

    return JSONResponse({"path": meta.path, "size": meta.size})


@app.get("/files")
def list_files() -> JSONResponse:
    """只列当前访问者自己的前缀 —— 按应用隔离是平台给的,按人隔离是应用自己的事。"""
    user = auth.current_user()
    try:
        metas = storage.list(f"{user.user_id}/")
    except errors.BishengSdkError as exc:
        # 存储不可用时抛错,不返回空列表:「没有附件」和「查不了」是两回事。
        return problem(exc, status=502)

    return JSONResponse([{"path": meta.path, "size": meta.size} for meta in metas])


@app.get("/files/{path:path}")
def download(path: str) -> Response:
    """应用自己把字节吐出去 —— 平台不提供绕过应用的直链。"""
    user = auth.current_user()
    if not path.startswith(f"{user.user_id}/"):
        # 别人的附件。平台保证「别的应用」拿不到,「别的人」要靠这一行。
        return JSONResponse(status_code=403, content={"error": "这个附件不属于你", "next_step": "回到列表页"})
    try:
        content = storage.get(path)
        meta = storage.stat(path)
    except errors.AttachmentNotFoundError as exc:
        return problem(exc, status=404)
    except errors.BishengSdkError as exc:
        return problem(exc, status=502)

    return Response(content=content, media_type=meta.content_type or "application/octet-stream")


@app.exception_handler(errors.PlatformIdentityMissingError)
def identity_missing(request: Request, exc: errors.PlatformIdentityMissingError) -> JSONResponse:
    """请求没经平台入口进来 —— 提示怎么访问,而不是 500 一个堆栈。"""
    return problem(exc, status=401)


if __name__ == "__main__":
    import uvicorn

    # 绑 0.0.0.0:平台从容器外探活与转发,绑 127.0.0.1 在本机测得好好的、上线必不健康。
    uvicorn.run(app, host="0.0.0.0", port=PORT)
