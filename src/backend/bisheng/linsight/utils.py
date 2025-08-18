import asyncio
import os
import uuid
from typing import List, Dict, Any

from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.database.models import LinsightSessionVersion, LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao, ExecuteTaskStatusEnum
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum
from bisheng.linsight.state_message_manager import LinsightStateMessageManager
from bisheng.settings import settings
from bisheng.utils import util
from bisheng.utils.minio_client import minio_client
from bisheng.utils.util import sync_func_to_async
from bisheng_langchain.linsight.event import ExecStep

# 灵思文件处理工具对应文件参数名
local_file_tool_dict = {
    "add_text_to_file": "file_path",
    "replace_file_lines": "file_path"
}

# 步骤事件额外处理工具对应参数名、
step_event_extra_tool_dict = {
    "add_text_to_file": "file_path",
    "replace_file_lines": "file_path",
    "read_text_file": "file_path"
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

            if not file_path:
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
            object_name = f"linsight/session_files/{execution_tasks[0].session_version_id}/{file_info['file_name']}"
            # Use async upload if available, otherwise wrap sync call
            await sync_func_to_async(minio_client.upload_minio)(
                bucket_name=minio_client.bucket,
                object_name=object_name,
                file_path=file_info["file_path"]
            )
            file_info["file_url"] = minio_client.clear_minio_share_host(minio_client.get_share_link(object_name))
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
            "file_id": uuid.uuid4().hex[:8]  # 生成唯一的文件ID
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
            final_file_info["file_url"] = minio_client.clear_minio_share_host(minio_client.get_share_link(object_name))
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


# 步骤事件额外处理
async def handle_step_event_extra(event: ExecStep, task_exec_obj) -> ExecStep:
    """
    处理步骤事件的额外逻辑
    :param task_exec_obj:
    :param event: 事件对象
    """
    logger.debug(f"步骤事件额外处理，call_id: {event.call_id}, name: {event.name}, status: {event.status}")
    try:
        if event.status == "end" and event.name in step_event_extra_tool_dict.keys():
            file_path = event.params.get(step_event_extra_tool_dict[event.name], "")
            if not file_path:
                return event

            file_name = os.path.basename(file_path)
            logger.debug(f"步骤事件额外处理，文件名: {file_name}")

            # 文件路径处理
            if not os.path.isabs(file_path):
                # 相对路径，转换为绝对路径
                file_path = os.path.join(task_exec_obj.file_dir, file_path)
                file_path = os.path.normpath(file_path)

            logger.debug(f"步骤事件额外处理，转换后的文件路径: {file_path}")

            if not os.path.exists(file_path):
                logger.error(f"步骤事件额外处理，文件不存在: {file_path}")
                return event

            file_md5 = await util.async_calculate_md5(file_path)

            # 判断文件是否已经上传过
            step_event_extra_files = task_exec_obj.step_event_extra_files
            if step_event_extra_files:
                existing_file = next((f for f in step_event_extra_files if f["file_md5"] == file_md5), None)
                if existing_file:
                    logger.debug(f"步骤事件额外处理，文件已存在: {existing_file['file_name']}, file_md5: {file_md5}")
                    event.extra_info["file_info"] = {
                        "file_name": file_name,
                        "file_md5": existing_file["file_md5"],
                        "file_url": existing_file["file_url"]
                    }
                    return event

            object_name = f"linsight/step_event/{task_exec_obj.session_version_id}/{uuid.uuid4().hex[:8]}.{file_name.split('.')[-1]}"
            logger.debug(f"步骤事件额外处理，上传文件到MinIO: {object_name}")

            # 上传文件到MinIO
            await sync_func_to_async(minio_client.upload_minio)(
                bucket_name=minio_client.bucket,
                object_name=object_name,
                file_path=file_path
            )

            event.extra_info["file_info"] = {
                "file_name": file_name,
                "file_md5": file_md5,
                "file_url": minio_client.clear_minio_share_host(
                    minio_client.get_share_link(object_name, minio_client.bucket))
            }

            # 添加到步骤事件额外文件列表
            task_exec_obj.step_event_extra_files.append(event.extra_info["file_info"])

    except Exception as e:
        logger.error(f"步骤事件额外处理异常: {e}")
        # 发生异常时，返回原始事件，不做任何修改

    return event


# 启动worker时检查是否有未完成的任务并终止
async def check_and_terminate_incomplete_tasks():
    """
    检查是否有未完成的任务并终止
    """

    # 清理Redis中的任务数据
    await LinsightStateMessageManager.cleanup_all_sessions()

    try:
        incomplete_linsight_session_versions = await LinsightSessionVersionDao.get_session_versions_by_status(
            status=SessionVersionStatusEnum.IN_PROGRESS)

        if not incomplete_linsight_session_versions:
            logger.info("没有未完成的灵思会话版本，跳过终止操作")
            return
        logger.warning(f"发现 {len(incomplete_linsight_session_versions)} 个未完成的灵思会话版本，准备终止它们")

        user_ids = [session.user_id for session in incomplete_linsight_session_versions]

        session_version_ids = [session.id for session in incomplete_linsight_session_versions]

        # 批量更新会话状态为已终止
        await LinsightSessionVersionDao.batch_update_session_versions_status(
            session_version_ids=session_version_ids,
            status=SessionVersionStatusEnum.TERMINATED
        )

        # 批量更新执行任务状态为已终止
        await LinsightExecuteTaskDao.batch_update_status_by_session_version_id(
            session_version_ids=session_version_ids,
            status=ExecuteTaskStatusEnum.TERMINATED,
            where=(
                LinsightExecuteTask.status != ExecuteTaskStatusEnum.SUCCESS,
                LinsightExecuteTask.status != ExecuteTaskStatusEnum.FAILED
            )

        )

        logger.warning(f"已终止 {len(incomplete_linsight_session_versions)} 个未完成的灵思会话版本和相关执行任务")

        system_config = await settings.aget_all_config()
        # 获取Linsight_invitation_code
        linsight_invitation_code = system_config.get("linsight_invitation_code", False)

        # 回滚邀请码
        if linsight_invitation_code:
            for user_id in user_ids:
                try:
                    await InviteCodeService.revoke_invite_code(user_id=user_id)
                    logger.info(f"已回滚用户 {user_id} 的邀请码")
                except Exception as e:
                    logger.error(f"回滚用户 {user_id} 的邀请码失败: {e}")

        else:
            logger.warning("系统配置中未启用 Linsight 邀请码功能，跳过回滚操作")

        logger.info("检查并终止未完成任务操作已完成")
    except Exception as e:
        logger.error(f"检查并终止未完成任务时发生异常: {e}")
        return
