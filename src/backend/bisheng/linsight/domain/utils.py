import asyncio
import os
import uuid
from typing import List, Dict, Any

from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.linsight.domain.models.linsight_execute_task import LinsightExecuteTaskDao, ExecuteTaskStatusEnum, \
    LinsightExecuteTask
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum, \
    LinsightSessionVersion
from bisheng.utils import util
from bisheng_langchain.linsight.event import ExecStep

# The corresponding file parameter name of the Inscription file processing tool
local_file_tool_dict = {
    "add_text_to_file": "file_path",
    "replace_file_lines": "file_path"
}

# Step event extra processing tool corresponding to parameter name,
step_event_extra_tool_dict = {
    "add_text_to_file": "file_path",
    "replace_file_lines": "file_path",
    "read_text_file": "file_path"
}


# Get all manipulated files in a task
async def get_all_files_from_session(execution_tasks: List[LinsightExecuteTask], file_details: List[Dict]) -> \
        list[Any] | list[Exception | BaseException | None]:
    """
    Get all manipulated files in a session
    :param file_details:
    :param execution_tasks: Execute Task List
    :return: List with file details
    """
    # Process File List
    all_from_session_files = file_details

    # Deduplication
    seen = set()
    all_from_session_files = [
        file for file in all_from_session_files
        if (file_tuple := (file["file_name"], file["file_path"], file["file_md5"])) not in seen and not seen.add(
            file_tuple)
    ]

    if not all_from_session_files:
        logger.warning("No files found that were manipulated in the session")
        return []

    # Upload files toMinIO
    async def upload_file_to_minio(file_info: Dict) -> dict | None:
        """Upload files toMinIOand returns file information"""
        try:
            minio_client = await get_minio_storage()
            object_name = f"linsight/session_files/{execution_tasks[0].session_version_id}/{file_info['file_name']}"
            # Use async upload if available, otherwise wrap sync call
            await minio_client.put_object(
                bucket_name=minio_client.bucket,
                object_name=object_name,
                file=file_info["file_path"]
            )
            file_info["file_url"] = object_name
            return file_info
        except Exception as e:
            logger.error(f"Upload files toMinIOKalah {file_info['file_name']}: {e}")
            return None

    # Upload files in parallel toMinIO
    upload_tasks = [
        upload_file_to_minio(file_info)
        for file_info in all_from_session_files
    ]
    upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)
    # Filter failed uploads
    all_from_session_files = [
        result for result in upload_results
        if result is not None and not isinstance(result, Exception)
    ]
    # Record failed uploads
    failed_uploads = [
        result for result in upload_results
        if isinstance(result, Exception)
    ]

    if failed_uploads:
        logger.warning(f"Some files failed to upload: {len(failed_uploads)} files")

    logger.debug(
        f"Number of files manipulated in the session: {len(all_from_session_files)}Document Description: {all_from_session_files}")

    return all_from_session_files


# Read File Directory File Details
async def read_file_directory(file_dir: str) -> List[Dict[str, str]]:
    """Read file details in file directory"""
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
            "file_id": uuid.uuid4().hex[:8]  # Generate unique filesID
        })

    return file_details


# Get the final result file
async def get_final_result_file(session_model: LinsightSessionVersion, file_details, answer) -> List[Dict]:
    """
    Get the final result file
    :param file_details:
    :param session_model: LinsightSessionVersion Model Instance
    :param answer: Answer content
    :return: List containing final result file information
    """
    # Final Result File
    final_result_files = []

    for file_info in file_details:
        file_name: str = file_info["file_name"]
        # Determine if the filename isanswerIn String
        if file_name in answer:
            # If the file name is in the answer, add it to the answer
            final_result_files.append({
                "file_name": file_name,
                "file_path": file_info["file_path"],
                "file_md5": file_info["file_md5"],
                "file_id": file_info["file_id"]
            })

    async def upload_file_to_minio(final_file_info: Dict) -> dict | None:
        """Upload files toMinIOand returns file information"""
        try:
            object_name = f"linsight/final_result/{session_model.id}/{final_file_info['file_name']}"
            # Use async upload if available, otherwise wrap sync call
            minio_client = await get_minio_storage()
            await minio_client.put_object(
                bucket_name=minio_client.bucket,
                object_name=object_name,
                file=final_file_info["file_path"]
            )
            final_file_info["file_url"] = object_name
            return final_file_info
        except Exception as e:
            logger.error(f"Upload files toMinIOKalah {final_file_info['file_name']}: {e}")
            return None

    # Upload files toMinIO (Parallel Processing)
    if final_result_files:
        upload_tasks = [
            upload_file_to_minio(final_file_info)
            for final_file_info in final_result_files
        ]

        upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

        # Filter failed uploads
        final_result_files = [
            result for result in upload_results
            if result is not None and not isinstance(result, Exception)
        ]

        # Record failed uploads
        failed_uploads = [
            result for result in upload_results
            if isinstance(result, Exception)
        ]
        if failed_uploads:
            logger.warning(f"Some files failed to upload: {len(failed_uploads)} files")

    return final_result_files


# Additional Handling of Step Events
async def handle_step_event_extra(event: ExecStep, task_exec_obj) -> ExecStep:
    """
    Additional logic for handling step events
    :param task_exec_obj:
    :param event: Event Object
    """
    logger.debug(
        f"extra processing of step events,call_id: {event.call_id}, name: {event.name}, status: {event.status}")
    try:
        if event.status == "end" and event.name in step_event_extra_tool_dict.keys():
            file_path = event.params.get(step_event_extra_tool_dict[event.name], "")
            if not file_path:
                return event

            file_name = os.path.basename(file_path)
            logger.debug(f"Step event extra processing, filename: {file_name}")

            # File path processing
            if not os.path.isabs(file_path):
                # relative paths, converting to absolute paths
                file_path = os.path.join(task_exec_obj.file_dir, file_path)
                file_path = os.path.normpath(file_path)

            logger.debug(f"Step event extra processing, converted file path: {file_path}")

            if not os.path.exists(file_path):
                logger.error(f"Step event extra processing, file does not exist: {file_path}")
                return event

            file_md5 = await util.async_calculate_md5(file_path)

            # Determine if the document has already been uploaded
            step_event_extra_files = task_exec_obj.step_event_extra_files
            if step_event_extra_files:
                existing_file = next((f for f in step_event_extra_files if f["file_md5"] == file_md5), None)
                if existing_file:
                    logger.debug(
                        f"Step event extra processing, file already exists: {existing_file['file_name']}, file_md5: {file_md5}")
                    event.extra_info["file_info"] = {
                        "file_name": file_name,
                        "file_md5": existing_file["file_md5"],
                        "file_url": existing_file["file_url"]
                    }
                    return event

            object_name = f"linsight/step_event/{task_exec_obj.session_version_id}/{uuid.uuid4().hex[:8]}.{file_name.split('.')[-1]}"
            logger.debug(f"Extra processing of step events, uploading files toMinIO: {object_name}")

            minio_client = await get_minio_storage()
            # Upload files toMinIO
            await minio_client.put_object(
                bucket_name=minio_client.bucket,
                object_name=object_name,
                file=file_path
            )

            event.extra_info["file_info"] = {
                "file_name": file_name,
                "file_md5": file_md5,
                "file_url": object_name
            }

            # Add to Step Event Extra File List
            task_exec_obj.step_event_extra_files.append(event.extra_info["file_info"])

    except Exception as e:
        logger.error(f"Step event extra handling exception: {e}")
        # When an exception occurs, return to the original event without modification

    return event


# Initiateworkerwhen checking for incomplete tasks and terminating
async def check_and_terminate_incomplete_tasks(node_id: str) -> None:
    """
    Check for incomplete tasks and terminate
    """

    from bisheng.linsight.worker import NodeManager

    redis_client = get_redis_client_sync()  # Get Redis Client
    node_manager = NodeManager(redis_client, node_id)  # Get Node Manager Instance

    try:
        # Get all incomplete tasks from the database
        incomplete_tasks = await LinsightSessionVersionDao.get_session_versions_by_status(
            status=SessionVersionStatusEnum.IN_PROGRESS
        )

        if not incomplete_tasks:
            return

        tasks_to_terminate = []
        user_ids_to_rollback = set()

        for session in incomplete_tasks:
            session_id = session.id

            # Check task ownership in Redis
            owner_key = f"linsight:task:owner:{session_id}"
            owner_node_id = await redis_client.get(owner_key)

            should_terminate = False

            if not owner_node_id:
                # No owned node, task needs to be cleaned up.
                should_terminate = True
                logger.warning(f"Task {session_id} has no owner in Redis. Marking as failed.")
            else:
                # There is an owned node, check if the node is alive
                is_alive = await node_manager.is_node_alive(owner_node_id)
                if not is_alive:
                    # Node is dead, task needs to be cleaned up.
                    should_terminate = True
                    logger.warning(f"Task {session_id} owner {owner_node_id} is dead. Marking as failed.")
                else:
                    # Node is alive, skip cleanup
                    logger.info(f"Task {session_id} is running on active node {owner_node_id}. Skipping.")

            if should_terminate:
                tasks_to_terminate.append(session_id)
                user_ids_to_rollback.add(session.user_id)

        # 3. 批量执行终止操作（只针对筛选出的任务）
        if tasks_to_terminate:
            await LinsightSessionVersionDao.batch_update_session_versions_status(
                session_version_ids=tasks_to_terminate,
                status=SessionVersionStatusEnum.FAILED,
                output_result={"error_message": "Worker node crash detected"}
            )

            # 更新 execution task 状态
            await LinsightExecuteTaskDao.batch_update_status_by_session_version_id(
                session_version_ids=tasks_to_terminate,
                status=ExecuteTaskStatusEnum.FAILED,
                where=(
                    LinsightExecuteTask.status != ExecuteTaskStatusEnum.SUCCESS,
                    LinsightExecuteTask.status != ExecuteTaskStatusEnum.FAILED
                )
            )

        logger.warning(f"Terminated {len(tasks_to_terminate)} incomplete tasks due to worker node crash.")

        system_config = await settings.aget_all_config()
        # DapatkanLinsight_invitation_code
        linsight_invitation_code = system_config.get("linsight_invitation_code", False)

        # Rollback invite code
        if linsight_invitation_code:
            for user_id in user_ids_to_rollback:
                try:
                    await InviteCodeService.revoke_invite_code(user_id=user_id)
                    logger.info(f"User Rolled Back {user_id} Invitation code for")
                except Exception as e:
                    logger.error(f"Rollback user {user_id} Invitation code failed for: {e}")

        else:
            logger.warning(
                "Not enabled in system configuration Linsight Invitation code function, skip rollback operation")

        logger.info("Check and terminate incomplete task action completed")
    except Exception as e:
        logger.error(f"Exception occurred while checking and terminating incomplete tasks: {e}")
        return
