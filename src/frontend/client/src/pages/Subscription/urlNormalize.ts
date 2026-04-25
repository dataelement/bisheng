// src/frontend/client/src/pages/Subscription/urlNormalize.ts

/** 标准化用户输入的 URL，用于队列去重与搜索匹配。
 *  - trim
 *  - 转小写
 *  - 去尾部 `/`
 */
export function normalizeUrlForSearch(value?: string): string {
    if (!value) return "";
    return value.trim().toLowerCase().replace(/\/+$/, "");
}
