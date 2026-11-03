// 工作流、助手、全部 (skill type 1 removed with the legacy skill module)
export enum AppType {
    ALL = 'all',
    FLOW = 'flow',
    ASSISTANT = 'assistant',
    HOSTED_APP = 'hosted_app',
}


export enum AppNumType {
    HOSTED_APP = 35,
    FLOW = 10,
    ASSISTANT = 5,
}

// 在共享类型文件中定义
export const AppTypeToNum = {
  [AppType.ASSISTANT]: AppNumType.ASSISTANT,
  [AppType.FLOW]: AppNumType.FLOW,
  [AppType.HOSTED_APP]: AppNumType.HOSTED_APP,
};

export const AppNumToType = {
  [AppNumType.ASSISTANT]: AppType.ASSISTANT,
  [AppNumType.FLOW]: AppType.FLOW,
  [AppNumType.HOSTED_APP]: AppType.HOSTED_APP,
}