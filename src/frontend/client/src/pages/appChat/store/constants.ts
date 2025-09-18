export const ERROR_CODES = {
    "10400": "error_assistant_not_found",
    "10401": "error_assistant_online_failed",
    "10402": "error_assistant_name_duplicate",
    "10403": "error_assistant_online_cannot_edit",
    "10410": "error_tool_name_exists",
    "10411": "error_tool_api_empty",
    "10412": "error_tool_not_found",
    "10413": "error_preset_tool_category_cannot_delete",
    "403": "error_no_permission",
    "404": "error_resource_not_found",
    "10300": "error_component_exists",
    "10301": "error_component_not_found",
    "10100": "error_create_training_task_failed",
    "10101": "error_training_set_required",
    "10102": "error_task_not_found",
    "10103": "error_task_status_error",
    "10104": "error_task_cancel_failed",
    "10105": "error_task_delete_failed",
    "10106": "error_task_publish_failed",
    "10107": "error_model_name_interface_modify_failed",
    "10108": "error_cancel_publish_failed",
    "10109": "error_invalid_training_params",
    "10110": "error_model_name_exists",
    "10120": "error_training_file_not_found",
    "10125": "error_get_gpu_info_failed",
    "10126": "error_get_model_list_failed",
    "10500": "error_skill_version_not_found",
    "10501": "error_current_version_cannot_delete",
    "10502": "error_version_name_exists",
    "10503": "error_skill_name_duplicate",
    "10520": "error_skill_not_found",
    "10521": "error_skill_online_cannot_edit",
    "10525": "error_workflow_online_cannot_edit",
    "10529": "error_workflow_name_duplicate",
    "10530": "error_template_name_exists",
    "10900": "error_knowledge_base_name_duplicate",
    "10901": "error_knowledge_base_embedding_required",
    "10910": "error_knowledge_base_version_segmentation_not_supported",
    "10800": "error_model_provider_name_duplicate",
    "10801": "error_model_duplicate",
    "10700": "error_tag_exists",
    "10701": "error_tag_not_found",
    "10600": "error_account_password_error",
    "10601": "error_password_expired",
    "10602": "error_password_not_set",
    "10603": "error_current_password_error",
    "10604": "error_account_logged_in_another_device",
    "10605": "error_username_exists",
    "10606": "error_user_group_role_required",
    "10610": "error_user_group_has_users_cannot_delete",
    "10920": "error_qa_knowledge_base_model_not_configured",
    "10930": "error_question_exists",
    "10527": "error_workflow_user_input_timeout",
    "10528": "error_node_execution_exceeded_max_times",
    "10531": "error_function_upgraded_need_recreate",
    "10532": "error_workflow_version_upgraded",
    "10540": "error_server_threads_full",
} as const

/**
 * 获取错误信息的国际化键值
 * @param errorCode 错误码
 * @returns 对应的国际化键值
 */
export const getErrorI18nKey = (errorCode: string): string => {
    return ERROR_CODES[errorCode as keyof typeof ERROR_CODES] || 'error_unknown'
}

/**
 * 错误码类型
 */
export type ErrorCode = keyof typeof ERROR_CODES