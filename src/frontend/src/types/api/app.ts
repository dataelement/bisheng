export type AppConfig = {
    env: string;
    uns_support: string[];
    office_url: string;
    dialog_tips: string;
    dialog_quick_search: string;
    websocket_url: string;
    pro: boolean;
    sso: boolean;
    application_usage_tips: boolean;
    enable_security_commitment: boolean;
    show_github_and_help: boolean;
    /** 上传文件大小限制 */
    uploaded_files_maximum_size: number;
    version: string;
    /** 注册入口 */
    enable_registration: boolean;
};