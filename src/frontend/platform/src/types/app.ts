// 工作流、助手、全部 (skill type 1 removed with the legacy skill module)
export enum AppType {
    ALL = 'all',
    FLOW = 'flow',
    ASSISTANT = 'assistant',
}


export enum AppNumType {
    FLOW = 10,
    ASSISTANT = 5,
}

// 在共享类型文件中定义
export const AppTypeToNum = {
  [AppType.ASSISTANT]: AppNumType.ASSISTANT,
  [AppType.FLOW]: AppNumType.FLOW,
};

export const AppNumToType = {
  [AppNumType.ASSISTANT]: AppType.ASSISTANT,
  [AppNumType.FLOW]: AppType.FLOW,
}