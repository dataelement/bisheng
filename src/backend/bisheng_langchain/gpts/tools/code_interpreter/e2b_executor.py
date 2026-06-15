import base64
import hashlib
import os
import tempfile
import uuid

from e2b.sandbox.filesystem.filesystem import EntryInfo, FileType, WriteEntry
from e2b_code_interpreter import Result, Sandbox
from loguru import logger

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import BaseExecutor

# F035 TC-4: copy-in/copy-out thresholds. The sandbox cannot reach MinIO, so the
# worker mediates all file transfer (design §9.3.9).
#  - SIZE_AUTOPUSH: working-set files at/under this size are auto-pushed into the
#    sandbox before each run (delta by md5). Larger files must be explicitly
#    declared in ``run(required_files=...)`` to avoid silent bulk transfer.
#  - SIZE_INLINE: copy-out products at/under this size may be inlined; larger
#    products are pointer-tracked (manifest) by the workspace backend.
SIZE_AUTOPUSH = 5 * 1024 * 1024  # 5 MB
SIZE_INLINE = 1 * 1024 * 1024  # 1 MB

_SANDBOX_ROOT = "/home/user/"


class E2bCodeExecutor(BaseExecutor):
    def __init__(
        self,
        minio: dict,
        api_key: str,
        domain: str = None,
        timeout: int = 300,
        file_list: list[WriteEntry] = None,
        keep_sandbox: bool = False,
        **kwargs,
    ):
        """
        timeout: Create sandbox with and keep it running for 300 seconds
        """
        super().__init__(minio, **kwargs)
        self.minio = minio
        self.api_key = api_key
        self.domain = domain
        self.timeout = timeout
        self.file_list = file_list
        self.keep_sandbox = keep_sandbox  # 是否保持一个sandbox, 默认只有在执行的时候才创建一个沙盒
        self.sandbox_file_cache = {}  # 缓存已经下载过的文件，避免重复下载

        # F035 TC-4: workspace integration. ``workspace_backend`` is injected by
        # the linsight worker; ``_pushed_md5`` tracks content already copied into
        # the sandbox so identical files are not re-pushed across runs.
        self.workspace_backend = kwargs.get("workspace_backend")
        self._pushed_md5: set[str] = set()

        if self.file_list:
            new_file_list = []
            for one in self.file_list:
                with open(one.data, "rb") as f:
                    new_file_list.append({"path": one.path, "data": f.read()})
            self.file_list = new_file_list

        self.sandbox = None
        if self.keep_sandbox:
            # Pre-warm the sandbox, but tolerate construction-time failures
            # (transient E2B unavailability / no network in tests): run() will
            # lazily re-init when needed.
            try:
                self.init_sandbox()
            except Exception:
                logger.warning("E2B sandbox pre-warm failed; will lazily init on run()")
                self.sandbox = None

    @property
    def description(self) -> str:
        return "A code interpreter that can execute python code. Input should be a valid python code. If you have any files outputted write them to `output/` relative to the execution path."

    def init_sandbox(self):
        if not self.sandbox:
            self.sandbox = Sandbox(domain=self.domain, api_key=self.api_key, timeout=self.timeout)
            self.sandbox.files.make_dir("output")  # 确保output目录存在
            if self.file_list:
                self.sandbox.files.write(self.file_list)
                # 初始化缓存信息
                files_info = self.sandbox.files.list("./")
                for file in files_info:
                    self.sandbox_file_cache[file.path] = file

    def run(self, code: str, required_files: list[str] = None):
        """
        Execute code in the E2B Code Interpreter sandbox.

        F035 TC-4: orchestrates workspace copy-in/copy-out around execution.
        :param code: The code to execute.
        :param required_files: workspace paths the script needs that exceed
            ``SIZE_AUTOPUSH``; they are streamed into the sandbox before the run.
            Smaller working-set files are auto-pushed (delta by md5).
        :return: dict with ``results``/``new_files`` (and ``copy_in_hint`` when a
            large file was used but not declared).
        """
        required_files = required_files or []
        if self.sandbox is None:
            self.init_sandbox()
        try:
            # copy-in: stage the working set into the sandbox
            copy_in_hint = self._copy_in(required_files)
            # snapshot AFTER copy-in so staged inputs are not mistaken for products
            pre_paths = self._snapshot_paths()

            execution = self.sandbox.run_code(code)
            results, file_list = self.parse_results(execution.results)

            # copy-out: enumerate new files vs the pre-run snapshot
            new_files = self._copy_out(pre_paths)

            result = {
                "results": results,
                "stdout": execution.logs.stdout,
                "stderr": execution.logs.stderr,
                "error": execution.error,
                "file_list": file_list,
                "new_files": new_files,
            }
            if copy_in_hint:
                result["copy_in_hint"] = copy_in_hint
            return result
        finally:
            # keep_sandbox reuses the running sandbox across calls; otherwise tear down
            if not self.keep_sandbox:
                self.close()

    # ------------------------------------------------------------------
    # F035 TC-4: workspace copy-in / copy-out
    # ------------------------------------------------------------------
    def _materialize_working_set(self) -> dict:
        """Return the workspace working set as ``{workspace_rel_path: bytes}``.

        The sandbox cannot reach MinIO, so the worker materializes the relevant
        workspace files (uploads/scratch the script may read) and hands them to
        the executor. Default is empty; the linsight worker overrides this (or it
        is patched in tests). TODO(Wave 2): wire to ``self.workspace_backend``
        via the worker-mediated transfer path (design §9.3.9).
        """
        return {}

    def _copy_in(self, required_files: list[str]) -> str | None:
        """Push working-set files into the sandbox. Returns a hint string when a
        large file was present but not declared in ``required_files``."""
        working_set = self._materialize_working_set()
        undeclared_large: list[str] = []
        for path, content in working_set.items():
            if not isinstance(content, bytes):
                content = content.encode("utf-8")
            md5 = hashlib.md5(content).hexdigest()
            if md5 in self._pushed_md5:
                continue  # delta push: identical content already in the sandbox
            if len(content) > SIZE_AUTOPUSH and path not in required_files:
                undeclared_large.append(path)
                continue
            self.sandbox.files.write(self._sandbox_path(path), content)
            self._pushed_md5.add(md5)
        if undeclared_large:
            return (
                "Some files exceed the auto-push size limit and were not staged. "
                f"Declare them in required_files to use them: {undeclared_large}"
            )
        return None

    def _snapshot_paths(self) -> set:
        """Set of sandbox file paths before a run, for copy-out diffing."""
        return {entry.path for entry in self._walk_sandbox()}

    def _copy_out(self, pre_paths: set) -> list[dict]:
        """Enumerate files created by the run and write products to the workspace.

        ``output/`` prefix => product (delivered); ``scratch/`` => intermediate.
        Returns ``[{path, size, is_product}]`` for each new file.
        """
        new_files: list[dict] = []
        for entry in self._walk_sandbox():
            if entry.path in pre_paths:
                continue
            rel_path = self._to_workspace_rel(entry.path)
            content = self.sandbox.files.read(entry.path, format="bytes")
            if not isinstance(content, bytes):
                content = content.encode("utf-8") if isinstance(content, str) else bytes(content)
            is_product = rel_path.startswith("output/")
            new_files.append({"path": rel_path, "size": len(content), "is_product": is_product})
            if self.workspace_backend is not None:
                # Large products are pointer-tracked by the backend; small ones inlined.
                self.workspace_backend.write(rel_path, content)
        return new_files

    def _walk_sandbox(self) -> list[EntryInfo]:
        """Flat list of all (non-hidden) file entries in the sandbox."""
        files: list[EntryInfo] = []
        for entry in self.sandbox.files.list("./"):
            if entry.name.startswith("."):
                continue
            if getattr(entry, "type", FileType.FILE) == FileType.FILE or entry.type == "file":
                files.append(entry)
        return files

    @staticmethod
    def _sandbox_path(workspace_rel_path: str) -> str:
        return workspace_rel_path.lstrip("/")

    @staticmethod
    def _to_workspace_rel(sandbox_path: str) -> str:
        return sandbox_path.replace(_SANDBOX_ROOT, "").lstrip("/")

    def run_code_with_one_sandbox(self, code: str) -> dict:
        """
        Execute code in the E2B Code Interpreter sandbox.
        :param code: The code to execute.
        :return: The result of the dict.
        """
        if self.sandbox is None:
            raise RuntimeError("Sandbox is destroyed.")
        execution = self.sandbox.run_code(code)
        results, file_list = self.parse_results(execution.results)
        return {
            "results": results,
            "stdout": execution.logs.stdout,
            "stderr": execution.logs.stderr,
            "error": execution.error,
            "file_list": file_list,
        }

    def parse_results(self, results: list[Result]):
        """
        Parse the results from the E2B Code Interpreter.
        :param results: The results from the code execution.
        :return: Parsed results.
        """
        parsed_results = []
        file_list = []
        for result in results:
            if result.text:
                parsed_results.append({"text": result.text})
            if result.html:
                parsed_results.append({"html": result.html})
            if result.markdown:
                parsed_results.append({"markdown": result.markdown})
            if result.svg:
                parsed_results.append({"svg": result.svg})
            if result.png:
                tmp_dir = tempfile.gettempdir()
                file_path = os.path.join(tmp_dir, uuid.uuid4().hex + ".png")
                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(result.png))
                file_list.append(self.upload_minio(f"{uuid.uuid4().hex}.png", file_path))
            if result.jpeg:
                tmp_dir = tempfile.gettempdir()
                file_path = os.path.join(tmp_dir, uuid.uuid4().hex + ".jpeg")
                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(result.jpeg))
                file_list.append(self.upload_minio(f"{uuid.uuid4().hex}.jpeg", file_path))
            if result.json:
                parsed_results.append({"json": result.json})
            if result.data:
                parsed_results.append({"data": result.data})
        if self.local_sync_path and os.path.exists(self.local_sync_path) and self.sandbox:
            # 将沙盒中的文件同步到本地目录
            files_info = self.sandbox.files.list("./")
            self.sync_files_to_local(files_info)

        return parsed_results, file_list

    def sync_files_to_local(self, files_info: list[EntryInfo]):
        if not files_info:
            return
        for file in files_info:
            # ignore hidden files
            if file.name.startswith("."):
                continue
            if file.type == FileType.FILE:
                if file.path not in self.sandbox_file_cache:
                    self.sandbox_file_cache[file.path] = file
                    self.download_file(file)
                # only download modified files
                if self.sandbox_file_cache[file.path].modified_time < file.modified_time:
                    self.download_file(file)
            else:
                new_files_info = self.sandbox.files.list(file.path)
                self.sync_files_to_local(new_files_info)

    def download_file(self, file_info: EntryInfo):
        relative_path = file_info.path.replace("/home/user/", "")
        local_path = os.path.join(self.local_sync_path, relative_path)
        local_dir = os.path.dirname(local_path)
        os.makedirs(local_dir, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(self.sandbox.files.read(file_info.path, format="bytes"))

    def close(self):
        if self.sandbox:
            self.sandbox.kill()
            self.sandbox = None


if __name__ == "__main__":
    e2b_api_key = os.environ.get("E2B_API_KEY")
    e2b_exec = E2bCodeExecutor(api_key=e2b_api_key, keep_sandbox=True, minio={}, local_sync_path="./e2b_output")
    result = e2b_exec.run(
        code="""import requests\nimport os
os.makedirs('./downloaded_wallpapers', exist_ok=True)
# 选定一个新的可靠高清风景图片链接
direct_image_url = 'https://images.unsplash.com/photo-1524758631624-e2822e304c36?ixid=MnwxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8&ixlib=rb-1.2.1&auto=format&fit=crop&w=1050&q=80'
output_path = './downloaded_wallpapers/wallpaper_1.jpg'
try:
    response = requests.get(direct_image_url, stream=True)
    if response.status_code == 200:
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        print(f'壁纸已成功下载到 {output_path}')
    else:
        print(f'请求失败，状态码: {response.status_code}')
except Exception as e:
    print(f'发生异常: {str(e)}')"""
    )
    print(result)
    print(11111)
    e2b_exec.close()

    # boxes = Sandbox.list(api_key=e2b_api_key)
    # for box in boxes:
    #     Sandbox.kill(sandbox_id=box.sandbox_id, api_key=e2b_api_key)
