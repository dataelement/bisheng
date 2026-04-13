export type User = {
    user_name: string;
    email: string | null;
    phone_number: string | null;
    dept_id: number | null;
    remark: string | null;
    delete: number;
    create_time: string;
    update_time: string;
    user_id: number;
    role: string;
    // Multi-tenant fields (F010)
    tenant_id?: number;
    tenant_name?: string;
    tenant_code?: string;
    tenant_logo?: string;
};

export type ROLE = {
    create_time: string
    id: number
    role_id: number
    remark: string
    role_name: string
    update_time: string
}

export type UserGroup = {
    id: number
    group_name: string
    adminUser: string
    group_admins: any[]
    createTime: string
    updateTime: string
    groupLimit?: number
}
