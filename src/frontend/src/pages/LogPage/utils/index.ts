export function transformModule(system: string): string {
    switch(system) {
        case 'chat': return '会话'
        case 'build': return '构建'
        case 'knowledge': return '知识库'
        case 'system': return '系统'
        default: return '转换失败'
    }
}

export function transformEvent(event: string): string {
    switch(event) {
        case 'create_chat': return '新建会话';
        case 'delete_chat': return '删除会话';
        case 'create_build': return '新建应用';
        case 'update_build': return '编辑应用';
        case 'delete_build': return '删除应用';
        case 'create_knowledge': return '新建知识库';
        case 'delete_knowledge': return '删除知识库';
        case 'upload_file': return '知识库上传文件';
        case 'delete_file': return '知识库删除文件';
        case 'update_user': return '用户编辑';
        case 'forbid_user': return '停用用户';
        case 'recover_user': return '启用用户';
        case 'create_user_group': return '新建用户组';
        case 'delete_user_group': return '删除用户组';
        case 'update_user_group': return '编辑用户组';
        case 'create_role': return '新建角色';
        case 'delete_role': return '删除角色';
        case 'update_role': return '编辑角色';
        case 'user_login': return '用户登录';
        default: return '转换失败'
    }
}

export function transformObjectType(object: string): string {
    switch(object) {
        case 'none': return '无'
        case 'workflow': return '工作流' // TODO 确认名称
        case 'flow': return '技能'
        case 'assistant': return '助手'
        case 'knowledge': return '知识库'
        case 'file': return '文件'
        case 'user_conf': return '用户配置'
        case 'user_group_conf': return '用户组配置'
        case 'role_conf': return '角色配置'
        default: return '转换失败'
    }
}