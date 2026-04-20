export type User = {
    user_name: string;
    external_id?: string | null;
    email: string | null;
    phone_number: string | null;
    dept_id: number | null;
    remark: string | null;
    delete: number;
    create_time: string;
    update_time: string;
    user_id: number;
    role: string;
    /** WEB_MENU third_id 列表（构建/知识等侧栏与动态路由） */
    web_menu?: string[];
    /** PRD 3.2.2：可进入用户组管理（超管 / 部门管理员） */
    can_manage_user_groups?: boolean;
    is_department_admin?: boolean;
    // Multi-tenant fields (F010)
    tenant_id?: number;
    tenant_name?: string;
    tenant_code?: string;
    tenant_logo?: string;
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
