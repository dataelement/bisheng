export type User = {
    user_name: string;
    external_id?: string | null;
    email: string | null;
    phone_number: string | null;
    /** 历史/业务侧部门标识，字符串居多；与组织树节点 ``id`` 不一定一致 */
    dept_id?: number | string | null;
    /** 主部门在 ``department`` 表中的内部主键，与 ``/departments/tree`` 的 ``id`` 对齐（/user/list 补充） */
    department_id?: number | null;
    remark: string | null;
    delete: number;
    create_time: string;
    update_time: string;
    user_id: number;
    role: string;
    /** WEB_MENU third_id 列表（构建/知识等侧栏与动态路由） */
    web_menu?: string[];
    /** 需审批模式：任意角色 quota_config.menu_approval_mode */
    menu_approval_mode?: boolean;
    /** PRD 3.2.2：可进入用户组管理（超管 / 部门管理员） */
    can_manage_user_groups?: boolean;
    is_department_admin?: boolean;
    // Multi-tenant fields (F010)
    tenant_id?: number;
    tenant_name?: string;
    tenant_code?: string;
    tenant_logo?: string;
    // Tenant-tree admin flags, populated by /user/info. Drive
    // conditional rendering of the admin scope selector, readonly
    // badges, and system-config panels.
    is_global_super?: boolean;
    is_child_admin?: boolean;
    leaf_tenant_id?: number;
    leaf_tenant_name?: string;
    /** Effective WEB_MENU: workbench area (v2.5 entry routing). */
    has_workbench?: boolean;
    /** Effective WEB_MENU: admin console area. */
    has_admin_console?: boolean;
    /** ``platform`` | ``workspace`` — post-login default when both → platform. */
    default_entry?: string;
};

export type ROLE = {
    id: number
    role_id?: number
    role_name: string
    role_type?: string
    department_id?: number | null
    department_name?: string | null
    /** 组织根 → 作用域部门 全路径（后端按 Department.path 解析） */
    department_scope_path?: string | null
    quota_config?: Record<string, any> | null
    user_count?: number
    creator_name?: string | null
    is_readonly?: boolean
    remark?: string
    create_time?: string
    update_time?: string
}

export type UserGroup = {
    id: number
    group_name: string
    adminUser: string
    group_admins: any[]
    createTime: string
    updateTime: string
    groupLimit?: number
    visibility?: string
}
