export type AppConfig = {
    env: string;
    uns_support: string[];
    office_url: string;
    dialog_tips: string;
    dialog_quick_search: string;
    websocket_url: string;
    pro: boolean;
    dashboard_pro: boolean;
    sso: boolean;
    application_usage_tips: boolean;
    show_github_and_help: boolean;
    version: string;
    /** 注册入口 */
    enable_registration: boolean;
    /** 最大上传文件大小 mb */
    uploaded_files_maximum_size: number;
    /** 音视频单文件最大上传大小 mb */
    uploaded_media_maximum_size?: number;
  enable_media_upload?: boolean;
    /** 是否部署 ETL4LM  */
    enable_etl4lm: boolean;
    /** F049: open capability layer switch (deployment level, needs a restart). */
    open_platform_enabled?: boolean;
    /**
     * F054: whether the app-factory runtime layer is deployed (deployment
     * level, needs a restart). Anonymously readable so the `apps/*` guide page
     * can decide what to say before anyone logs in.
     */
    app_runtime_enabled?: boolean;
};