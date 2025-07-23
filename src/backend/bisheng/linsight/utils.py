import asyncio
import os
from typing import List, Dict, Any, Coroutine
from loguru import logger
from bisheng.database.models import LinsightSessionVersion, LinsightExecuteTask
from bisheng.utils import util
from bisheng.utils.minio_client import minio_client
from bisheng.utils.util import sync_func_to_async

# 灵思文件处理工具对应文件参数名
local_file_tool_dict = {
    "write_text_file": "file_path",
    "replace_file_lines": "file_path"
}


# 获取任务中的所有操作过的文件
async def get_all_files_from_session(execution_tasks: List[LinsightExecuteTask], file_details: List[Dict]) -> list[
                                                                                                                  Any] | \
                                                                                                              list[
                                                                                                                  Exception | BaseException | None]:
    """
    获取会话中所有操作过的文件
    :param file_details:
    :param execution_tasks: 执行任务列表
    :return: 包含文件详情的列表
    """
    # 过程文件列表
    all_from_session_files = []
    for task in execution_tasks:
        if task.history is None or not task.history:
            continue

        for history in task.history:
            history_name = history.get("name", "")
            if history_name not in local_file_tool_dict.keys():
                continue

            file_path = history.get("params", {}).get(local_file_tool_dict[history_name], "")

            if not file_path or not os.path.exists(file_path):
                continue

            file_name = os.path.basename(file_path)

            # 从 file_details 中查找文件信息
            file_info = next((f for f in file_details if f["file_name"] == file_name), None)

            # 如果文件信息不存在，则跳过
            if not file_info:
                continue

            all_from_session_files.append(file_info)

    # 去重
    seen = set()
    all_from_session_files = [
        file for file in all_from_session_files
        if (file_tuple := (file["file_name"], file["file_path"], file["file_md5"])) not in seen and not seen.add(
            file_tuple)
    ]

    if not all_from_session_files:
        logger.warning("没有找到会话中操作过的文件")
        return []

    # 上传文件到MinIO
    async def upload_file_to_minio(file_info: Dict) -> dict | None:
        """上传文件到MinIO并返回文件信息"""
        try:
            object_name = f"linsight/session_files/{file_info['file_id']}/{file_info['file_name']}"
            # Use async upload if available, otherwise wrap sync call
            await sync_func_to_async(minio_client.upload_minio)(
                bucket_name=minio_client.bucket,
                object_name=object_name,
                file_path=file_info["file_path"]
            )
            file_info["file_url"] = object_name
            return file_info
        except Exception as e:
            logger.error(f"上传文件到MinIO失败 {file_info['file_name']}: {e}")
            return None

    # 并行上传文件到MinIO
    upload_tasks = [
        upload_file_to_minio(file_info)
        for file_info in all_from_session_files
    ]
    upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)
    # 过滤掉失败的上传结果
    all_from_session_files = [
        result for result in upload_results
        if result is not None and not isinstance(result, Exception)
    ]
    # 记录失败的上传
    failed_uploads = [
        result for result in upload_results
        if isinstance(result, Exception)
    ]

    if failed_uploads:
        logger.warning(f"部分文件上传失败: {len(failed_uploads)} 个文件")


    logger.debug(f"会话中操作过的文件数量: {len(all_from_session_files)}，文件详情: {all_from_session_files}")

    return all_from_session_files


# 读取文件目录文件详情
async def read_file_directory(file_dir: str) -> List[Dict[str, str]]:
    """读取文件目录中的文件详情"""
    if not file_dir or not os.path.exists(file_dir):
        return []

    files = util.read_files_in_directory(file_dir)
    file_details = []
    for file in files:
        file_md5 = await util.async_calculate_md5(file)
        file_details.append({
            "file_name": os.path.basename(file),
            "file_path": file,
            "file_md5": file_md5,
            "file_id": os.path.basename(file).rsplit('.', 1)[0]
        })

    return file_details


# 获取最终结果文件
async def get_final_result_file(session_model: LinsightSessionVersion, file_details, answer) -> List[Dict]:
    """
    获取最终结果文件
    :param file_details:
    :param session_model: LinsightSessionVersion 模型实例
    :param answer: 答案内容
    :return: 包含最终结果文件信息的列表
    """
    # 最终结果文件
    final_result_files = []

    for file_info in file_details:
        file_name: str = file_info["file_name"]
        # 判断文件名是否在answer字符串中
        if file_name in answer:
            # 如果文件名在答案中，添加到答案中
            final_result_files.append({
                "file_name": file_name,
                "file_path": file_info["file_path"],
                "file_md5": file_info["file_md5"],
                "file_id": file_info["file_id"]
            })

    async def upload_file_to_minio(final_file_info: Dict) -> dict | None:
        """上传文件到MinIO并返回文件信息"""
        try:
            object_name = f"linsight/final_result/{session_model.id}/{final_file_info['file_name']}"
            # Use async upload if available, otherwise wrap sync call
            await sync_func_to_async(minio_client.upload_minio)(
                bucket_name=minio_client.bucket,
                object_name=object_name,
                file_path=final_file_info["file_path"]
            )
            final_file_info["file_url"] = object_name
            return final_file_info
        except Exception as e:
            logger.error(f"上传文件到MinIO失败 {final_file_info['file_name']}: {e}")
            return None

    # 上传文件到MinIO (并行处理)
    if final_result_files:
        upload_tasks = [
            upload_file_to_minio(final_file_info)
            for final_file_info in final_result_files
        ]

        upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

        # 过滤掉失败的上传结果
        final_result_files = [
            result for result in upload_results
            if result is not None and not isinstance(result, Exception)
        ]

        # 记录失败的上传
        failed_uploads = [
            result for result in upload_results
            if isinstance(result, Exception)
        ]
        if failed_uploads:
            logger.warning(f"部分文件上传失败: {len(failed_uploads)} 个文件")

    return final_result_files
