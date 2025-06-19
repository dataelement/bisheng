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
    show_github_and_help: boolean;
    version: string;
    enable_security_commitment: boolean;
    /** 注册入口 */
    enable_registration: boolean;
    /** 最大上传文件大小 mb */
    uploaded_files_maximum_size: number;
    /** 是否部署 ETL4LM  */
    enable_etl4lm: boolean;
};