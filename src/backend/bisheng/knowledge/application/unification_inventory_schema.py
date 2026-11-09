"""Closed operational inventory wire schemas; no SQL or migration authority."""


def _spec(text):
    return dict(item.split(":", 1) for item in text.split())


# These are wire allowlists, deliberately independent of dataclass introspection.
_SCHEMAS = {
    "evidence_material": _spec(
        "material_kind:str environment:str writer_contract_version:str tenant_inventory_digest:hash material_ref:descriptor"
    ),
    "queued_task_orphan": _spec(
        "task_kind:str task_id:str space_id:int? file_id:int? document_id:int? version_id:int? payload_tenant_id:positive? state:str reason:str configuration_digest:hash record_digest:hash"
    ),
    "permission_plan": _spec(
        "tenant_id:positive resource_type:str resource_id:str target_resource_type:str plan_checksum:hash before_digest:hash after_grants_digest:hash visibility_deltas_digest:hash expected_use_changes_digest:hash"
    ),
    "resource": _spec(
        "tenant_id:positive id:positive type:int user_id:int? state:int? model:str? index_name:str? collection_name:str? creation_request_id:str? creation_payload_hash:str? old_business_digest:hash neutral_digest:hash"
    ),
    "file": _spec(
        "id:positive tenant_id:positive knowledge_id:positive file_type:int level:int? file_level_path:str? status:int? file_source:str? file_size:int? object_name:str? preview_file_object_name:str? bbox_object_name:str? thumbnails:str? html_snapshot_object_name:str? row_digest:hash split_rule_digest:hash user_metadata_digest:hash"
    ),
    "document": _spec(
        "id:positive knowledge_id:positive file_level_path:str? level:int? primary_version_id:int? parent_tenant_id:int? parent_knowledge_type:int? row_digest:hash"
    ),
    "version": _spec(
        "id:positive document_id:positive knowledge_file_id:positive version_no:int is_primary:bool knowledge_id:int? parent_tenant_id:int? file_knowledge_id:int? file_tenant_id:int? file_type:int? file_space_tenant_id:int? row_digest:hash"
    ),
    "qa": _spec(
        "id:positive tenant_id:positive knowledge_id:positive user_id:int? source:int? status:int? row_digest:hash"
    ),
    "tag": _spec("id:positive tenant_id:positive user_id:int business_type:str business_id:str? row_digest:hash"),
    "tag_link": _spec(
        "id:positive tenant_id:positive user_id:int tag_id:int resource_id:str resource_type:int row_digest:hash"
    ),
    "tag_library": _spec(
        "id:positive tenant_id:positive owner_knowledge_id:int? user_id:int tag_count:int is_builtin:bool row_digest:hash"
    ),
    "department_space": _spec(
        "id:positive tenant_id:positive department_id:int space_id:int created_by:int approval_enabled:bool sensitive_check_enabled:bool is_hidden:bool row_digest:hash"
    ),
    "tenant": _spec(
        "id:positive status:str parent_tenant_id:int? root_dept_id:int? share_default_to_children:int quota_digest:hash row_digest:hash"
    ),
    "membership": _spec(
        "id:positive user_id:int tenant_id:positive is_default:int status:str is_active:int? last_access_time:str? join_time:str? row_digest:hash"
    ),
    "space_membership_header": _spec(
        "knowledge_id:positive tenant_id:positive knowledge_type:int creator_user_id:int? member_count:nonnegative row_digest:hash"
    ),
    "space_member": _spec(
        "tenant_id:positive knowledge_id:positive id:positive business_id:str business_type:str user_id:int user_role:str status:str membership_source:str department_admin_promoted_from_role:str? relation:str? grant_subject_type:str? grant_subject_id:int? grant_relation:str? grant_include_children:bool grant_model_id:str? grant_binding_key:str? is_pinned:bool create_time:str? update_time:str? row_digest:hash"
    ),
    "department": _spec(
        "id:positive tenant_id:positive parent_id:int? path:str status:str is_deleted:int is_tenant_root:int mounted_tenant_id:int? update_time:str? row_digest:hash"
    ),
    "role": _spec(
        "id:positive tenant_id:positive role_type:str department_id:int? knowledge_space_file_limit:int? update_time:str? quota_digest:hash row_digest:hash"
    ),
    "user_role": _spec(
        "id:int user_id:int role_id:int tenant_id:positive create_time:str? update_time:str? row_digest:hash"
    ),
    "creator": _spec("user_id:positive exists:bool delete:int?"),
    "role_fact": _spec(
        "id:positive exists:bool tenant_id:int? role_type:str? department_id:int? knowledge_space_file_limit:int? update_time:str? quota_digest:hash row_digest:hash"
    ),
    "physical_index": _spec(
        "tenant_id:positive space_id:positive index_name:str? collection_name:str? es_exists:bool milvus_exists:bool es_mapping_digest:hash? milvus_schema_digest:hash? es_count:nonnegative? milvus_count:nonnegative? identifier_compatible:bool"
    ),
    "physical_object": _spec(
        "tenant_id:positive space_id:positive file_id:positive object_kind:str object_key:key exists:bool size:nonnegative? etag:str?"
    ),
    "queued_task": _spec(
        "tenant_id:positive task_kind:str task_id:str space_id:int? file_id:int? document_id:int? version_id:int? state:str configuration_digest:hash record_digest:hash"
    ),
    "broker_task": _spec(
        "tenant_id:positive? task_kind:str? task_id:str space_id:positive? file_id:positive? document_id:positive? version_id:positive? state:str configuration_digest:hash record_digest:hash header_tenant_id:positive?"
    ),
    "fga_tuple": _spec("user:str relation:str object:str"),
    "manifest_entry": _spec(
        "section:str scope:str tenant_id:positive? page_index:nonnegative record_count:nonnegative descriptor:descriptor level:nonnegative"
    ),
    "run": _spec(
        "writer_contract_version:str environment:str tenant_count:positive tenant_inventory_digest:hash backup_ref:descriptor schema_ref:descriptor catalog_digest:hash authorization_model_checksum:hash baseline_ref:descriptor?"
    ),
    "conversion_plan": _spec(
        "tenant_id:positive resource_id:positive original_type:int target_type:int action:str business_digest:hash"
    ),
    "source_decision": _spec(
        "tenant_id:positive source_type:str source_id:str source_version:str slot_key:str target_type:str target_id:str exists:bool disposition:str revision_digest:hash"
    ),
    "quota_usage": _spec(
        "tenant_id:positive personal_space_count:nonnegative department_space_count:nonnegative stored_bytes:nonnegative configuration_digest:hash"
    ),
    "resource_mode": _spec(
        "id:positive tenant_id:positive resource_type:str resource_id:str mode:str parent_type:str? parent_id:str? version:int projection_state:str operation_id:int?"
    ),
    "grant": _spec(
        "id:positive tenant_id:positive resource_type:str resource_id:str model_key:str state:str version:int projection_state:str"
    ),
    "assignee": _spec(
        "id:positive grant_id:positive tenant_id:positive subject_type:str subject_id:str userset_relation:str? include_children:bool source_type:str source_ref:str source_locator:str source_fingerprint:hash projected_subject:str protected:bool state:str version:int"
    ),
    "visible_source": _spec("id:positive source:source"),
    "source_contribution": _spec(
        "tenant_id:positive resource_type:str resource_id:str visibility_class:str projected_subject:str source_kind:str source_owner_key:str source_locator:str source_fingerprint:hash contribution_fingerprint:hash model_key:str? source_version:nonnegative tuple_fingerprint:hash state:str operation_id:positive? migration_item_id:positive?"
    ),
    "catalog_release": _spec(
        "id:positive release_key:str version:int checksum:hash required_authorization_model_release_id:int status:str write_fenced:bool predecessor_id:int? commit_checksum:str? draft_owner_id:int idempotency_key:str projection_checkpoint:int expires_at:str? published_at:str?"
    ),
    "authorization": _spec(
        "id:positive environment:str store_id:str model_id:str model_checksum:hash required_relations_checksum:hash status:str model_version:str predecessor_model_id:str? openfga_version:str"
    ),
    "catalog_action": _spec("code:str name:str level:int? active:bool resource_types:strings sort_order:int"),
    "permission_model": _spec(
        "id:positive model_key:str name:str normalized_name:str kind:str config_scope:str derived_level:int? active:bool allow_same_level:bool selected_action_codes:strings effective_action_codes:strings visibility_only_resource_types:strings visibility_level:int? legacy_source_key:str? retired_use_level_floor:int?"
    ),
}

_CONVERSION_COMMON = _spec(
    "schema_version:int run_id:str writer_contract_version:str tenant_id:positive command_key:hash operation:str"
)
_CONVERSION_FIELDS = {
    "resource_conversion": "knowledge_id:positive before_business_digest:hash after_business_digest:hash before_neutral_digest:hash after_neutral_digest:hash after_inventory_business_revision_digest:hash after_owner_configuration_digest:hash target_type:int target_is_released:bool target_migration_origin:str creator_user_id:positive membership_action:str before_member_count:nonnegative before_member_digest:hash existing_creator_member_id:positive? creator_template_digest:hash creator_planned_at:str?",
    "initialize_v1": "knowledge_id:positive file_id:positive file_business_digest:hash before_relation_digest:hash natural_key:hash document_template_digest:hash version_template_digest:hash file_level_path:str? level:int? planned_at:str",
    "tag_conversion": "tag_id:positive knowledge_id:positive before_digest:hash after_digest:hash from_business_type:str to_business_type:str",
    "tag_link_conversion": "link_id:positive file_id:positive knowledge_id:positive tag_id:positive before_digest:hash after_digest:hash? from_type:int to_type:int action:str survivor_link_id:positive survivor_digest:hash",
    "default_conversion": "row_id:positive key:str before_raw_row_digest:hash before_configuration_digest:hash after_configuration_digest:hash after_business_revision_digest:hash before_refs_digest:hash after_refs_digest:hash action:str selected_linsight_id:str? selected_chat_id:str? drop_task_model:bool drop_executor_mode:bool algorithm_version:str provenance:provenance",
}
for _tag, _fields in _CONVERSION_FIELDS.items():
    _SCHEMAS[_tag] = _CONVERSION_COMMON | _spec(_fields)
