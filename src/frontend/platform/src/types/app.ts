// 工作流、助手、托管应用、全部 (skill type 1 removed with the legacy skill module)
export enum AppType {
    ALL = 'all',
    FLOW = 'flow',
    ASSISTANT = 'assistant',
    /** F054 hosted application — the third platform application type. */
    HOSTED_APP = 'app',
}


/**
 * Numeric type codes. These mirror the backend `FlowType` enum one for one, so
 * values may only be **added**: changing an existing one desynchronises the
 * UNION branch the app list is built from.
 */
export enum AppNumType {
    FLOW = 10,
    ASSISTANT = 5,
    /** F054 — avoids the taken 5/10/15/20/25/30 slots. */
    HOSTED_APP = 35,
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
