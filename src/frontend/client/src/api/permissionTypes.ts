export type ResourceType =
  | "knowledge_space"
  | "knowledge_library"
  | "folder"
  | "knowledge_file"
  | "workflow"
  | "assistant"
  | "tool"
  | "channel"
  | "dashboard"
  | "linsight_skill";

export type SubjectType = "user" | "department" | "user_group";
export type PermissionActionLevel = 1 | 2 | 3 | 4;
export type ResourcePermissionMode = "INHERIT" | "CUSTOM";

export interface GrantablePermissionModel {
  key: string;
  name: string;
  level: PermissionActionLevel | null;
  active: boolean;
}

export interface CreationPermissionContext {
  catalog_release_id: number;
  can_configure_initial_permissions: boolean;
  grantable_models: GrantablePermissionModel[];
}

export interface InitialPermissionGrant {
  model_key: string;
  subject: PermissionGrantSubjectInput;
}

export interface InitialPermissionsPayload {
  expected_catalog_release_id: number;
  grants: InitialPermissionGrant[];
}

export interface RawInitialPermissionResult {
  status: "succeeded" | "failed";
  resource_version?: number | null;
  assignee_ids?: string[];
  error_code?: number | null;
  message?: string | null;
}

export interface InitialPermissionResult {
  status: "succeeded" | "failed";
  resourceVersion?: number;
  assigneeIds: string[];
  errorCode: number | null;
  message?: string;
}

export interface ResourcePermissionContext {
  mode: ResourcePermissionMode;
  parent_type: ResourceType | null;
  parent_id: string | null;
  resource_version: number;
  catalog_release_id: number;
  projection_state: string;
  can_manage_permission: boolean;
}

export interface PermissionGrantSubject {
  type: SubjectType;
  id: string;
  name: string | null;
}

export interface PermissionGrantSource {
  type: string;
  include_children: boolean;
  userset_relation?: string | null;
}

export interface PermissionGrantAssignee {
  assignee_id: string;
  assignee_version: number;
  subject: PermissionGrantSubject;
  model: GrantablePermissionModel;
  source: PermissionGrantSource;
  scope: "LOCAL" | "INHERITED";
  inherited_from: string | null;
  inherited_from_name?: string | null;
  protected: boolean;
  editable: boolean;
}

export interface PermissionGrantCursorPage {
  data: PermissionGrantAssignee[];
  page_size: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface MyResourcePermissions {
  mode: ResourcePermissionMode;
  actions: string[];
  sources: PermissionGrantSource[];
  roster_complete: boolean;
}

export interface PermissionGrantSubjectInput {
  type: SubjectType;
  id: string;
  userset_relation?: string | null;
  include_children?: boolean;
}

export type PermissionGrantMutationChange =
  | {
      op: "ADD";
      model_key: string;
      subject: PermissionGrantSubjectInput;
    }
  | {
      op: "MOVE";
      assignee_id: string;
      expected_assignee_version: number;
      target_model_key: string;
    }
  | {
      op: "REMOVE";
      assignee_id: string;
      expected_assignee_version: number;
    };

export interface MutateResourceGrantsRequest {
  idempotency_key: string;
  expected_resource_version: number;
  expected_catalog_release_id: number;
  changes: PermissionGrantMutationChange[];
}

export interface MutateResourceGrantsResult {
  resource_version: number;
  items: PermissionGrantAssignee[];
}

export interface CreatePermissionModeDraftRequest {
  target_mode: ResourcePermissionMode;
  expected_resource_version: number;
  expected_catalog_release_id: number;
}

export interface PermissionModeDraft {
  draft_id: string;
  target_mode: ResourcePermissionMode;
  impact_checksum: string;
  affected_assignees: number;
  expires_at: string;
}

export interface ApplyPermissionModeDraftRequest {
  idempotency_key: string;
  expected_resource_version: number;
  expected_catalog_release_id: number;
  confirmed: true;
}

export interface ApplyPermissionModeDraftResult {
  applied: boolean;
  mode: ResourcePermissionMode;
  resource_version: number;
}

export interface CheckResourceActionRequest {
  resource_type: ResourceType;
  resource_id: string;
  action: string;
}

export interface SelectedSubject {
  type: SubjectType;
  id: number;
  name: string;
  include_children?: boolean;
  externalId?: string | null;
  departmentPath?: string | null;
  departmentTreePath?: string;
}
