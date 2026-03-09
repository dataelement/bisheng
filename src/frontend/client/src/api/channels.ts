import request from "./request";

// 排序方式
export enum SortType {
    RECENT_UPDATE = "recent_update",    // 最近更新
    RECENT_ADDED = "recent_added",      // 最近添加
    NAME = "name"                        // 频道名称
}

// 频道权限
export enum ChannelRole {
    CREATOR = "creator",      // 创建者
    ADMIN = "admin",          // 管理员
    MEMBER = "member"         // 普通成员
}

// 子频道接口
export interface SubChannel {
    id: string;
    name: string;
    articleCount: number;
}

// 频道接口
export interface Channel {
    id: string;
    name: string;
    description?: string;
    creator: string;           // 创建者用户名
    creatorId: string;         // 创建者ID
    subscriberCount: number;   // 订阅人数
    articleCount: number;      // 文章数量
    unreadCount: number;       // 未读数量
    role: ChannelRole;         // 当前用户的角色
    isPinned: boolean;         // 是否置顶
    createdAt: string;         // 创建时间
    updatedAt: string;         // 最近更新时间
    subChannels: SubChannel[]; // 子频道列表
}

// 文章接口
export interface Article {
    id: string;
    title: string;
    url: string;               // 原文链接
    content: string;           // 正文
    summary?: string;          // 摘要
    coverImage?: string;       // 封面图
    sourceName: string;        // 信息源名称
    sourceAvatar?: string;     // 信息源头像
    sourceId: string;          // 信息源ID
    channelId: string;         // 所属频道ID
    subChannelId?: string;     // 所属子频道ID
    isRead: boolean;           // 是否已读
    publishedAt: string;       // 发布时间
    createdAt: string;         // 创建时间（加入频道的时间）
}

/**
 * 获取频道列表
 */
export async function getChannelsApi(params: {
    type: "created" | "subscribed";  // 我创建的 / 我关注的
    sortBy?: SortType;
}): Promise<Channel[]> {
    return await request.get(`/api/v1/channels`, { params });
}

/**
 * 创建频道
 */
export async function createChannelApi(data: {
    name: string;
    description?: string;
    subChannels?: string[];  // 子频道名称列表
}): Promise<Channel> {
    return await request.post(`/api/v1/channels`, data);
}

/**
 * 更新频道
 */
export async function updateChannelApi(channelId: string, data: {
    name?: string;
    description?: string;
    subChannels?: string[];
}): Promise<Channel> {
    return await request.put(`/api/v1/channels/${channelId}`, data);
}

/**
 * 订阅频道
 */
export async function subscribeChannelApi(channelId: string): Promise<void> {
    return await request.post(`/api/v1/channels/${channelId}/subscribe`);
}

/**
 * 取消订阅频道
 */
export async function unsubscribeChannelApi(channelId: string): Promise<void> {
    return await request.post(`/api/v1/channels/${channelId}/unsubscribe`);
}

/**
 * 解散频道
 */
export async function deleteChannelApi(channelId: string): Promise<void> {
    return await request.delete(`/api/v1/channels/${channelId}`);
}

/**
 * 置顶/取消置顶频道
 */
export async function pinChannelApi(channelId: string, pinned: boolean): Promise<void> {
    return await request.post(`/api/v1/channels/${channelId}/pin`, { pinned });
}

/**
 * 获取频道文章列表
 */
export async function getArticlesApi(params: {
    channelId: string;
    subChannelId?: string;     // 子频道ID（可选）
    search?: string;           // 搜索关键词
    sourceIds?: string[];      // 信息源ID列表
    onlyUnread?: boolean;      // 仅看未读
    page?: number;
    pageSize?: number;
}): Promise<{
    data: Article[];
    total: number;
    hasMore: boolean;
}> {
    return await request.get(`/api/v1/channels/${params.channelId}/articles`, { params });
}

/**
 * 标记文章为已读
 */
export async function markArticleAsReadApi(articleId: string): Promise<void> {
    return await request.post(`/api/v1/articles/${articleId}/read`);
}

/**
 * 获取信息源列表
 */
export async function getSourcesApi(channelId: string): Promise<{
    id: string;
    name: string;
    avatar?: string;
}[]> {
    return await request.get(`/api/v1/channels/${channelId}/sources`);
}

/**
 * 分享频道
 */
export async function shareChannelApi(channelId: string): Promise<{
    shareUrl: string;
}> {
    return await request.post(`/api/v1/channels/${channelId}/share`);
}

// 频道预览数据（分享链接访问时返回）
export interface ChannelPreview {
    id: string;
    name: string;
    description?: string;
    creator: string;
    creatorAvatar?: string;
    articleCount: number;
    subscriberCount: number;
    sources: { id: string; name: string; avatar?: string }[];
    articles: Article[];
    isSubscribed: boolean;       // 当前用户已订阅
    needsApproval: boolean;      // 频道需要审批才能订阅
    isPending: boolean;          // 当前用户已申请，等待审批
    isDeleted: boolean;          // 频道已删除
}

/**
 * 获取频道预览信息（分享链接用）
 */
export async function getChannelPreviewApi(channelId: string): Promise<ChannelPreview> {
    return await request.get(`/api/v1/channels/${channelId}/preview`);
}

/**
 * ===== 频道管理（manager）相关接口 =====
 * 这些是你提供的 /api/v1/channel/manager/* 系列，用于频道创建、信息源管理、广场等。
 */

// 信息源业务类型
export type ChannelBusinessType = "wechat" | "website";

// manager 侧的信息源结构（根据后端约定，可后续再细化）
export interface ManagerSource {
    id: string;
    name: string;
    avatar?: string;
    url?: string;
    business_type: ChannelBusinessType;
}

// 单条筛选规则
export interface ManagerChannelRuleItem {
    rule_type?: string;        // 规则类型，例如 include / exclude 等
    keywords?: string[];       // 关键词列表
    channel_type?: string;     // 频道类型（如有）
    name?: string;             // 规则名称（如有）
}

// 一组条件 + 关系
export interface ManagerChannelFilterRule {
    rules?: ManagerChannelRuleItem[];
    relation?: string;         // and / or 等
}

// 创建频道（manager）接口入参
export interface CreateManagerChannelPayload {
    name: string;                         // 频道名称（必填）
    source_list: string[];                // 信息源 ID 列表（必填）
    visibility: string;                   // 可见性（如 private / approval / public）
    filter_rules: ManagerChannelFilterRule[]; // 筛选规则（必填）
    channel_type?: string;                // 频道类型（可选）
    is_released?: boolean;                // 是否发布（可选）
}

/**
 * POST /api/v1/channel/manager/create
 * 创建频道（带信息源 + 过滤规则）
 */
export async function createManagerChannelApi(
    data: CreateManagerChannelPayload
): Promise<any> {
    return await request.post(`/api/v1/channel/manager/create`, data);
}

/**
 * GET /api/v1/channel/manager/list_sources
 * 获取信息源列表（公众号 / 网站）
 */
export async function listManagerSourcesApi(params: {
    business_type?: ChannelBusinessType;  // wechat / website
    page?: number;
    page_size?: number;
}): Promise<{
    data: ManagerSource[];
    total: number;
}> {
    return await request.get(`/api/v1/channel/manager/list_sources`, { params });
}

/**
 * POST /api/v1/channel/manager/add_website_source
 * 添加网站信息源
 */
export async function addWebsiteSourceApi(body: {
    url: string;
}): Promise<any> {
    return await request.post(`/api/v1/channel/manager/add_website_source`, body);
}

/**
 * POST /api/v1/channel/manager/add_wechat_source
 * 添加公众号信息源
 * （具体字段以后如果后端定死了可以再细化类型，目前留为通用 body）
 */
export async function addWechatSourceApi(body: {
    url?: string;
    account?: string;
    [key: string]: any;
}): Promise<any> {
    return await request.post(`/api/v1/channel/manager/add_wechat_source`, body);
}

/**
 * POST /api/v1/channel/manager/crawl
 * 信息源网址临时爬取
 */
export async function crawlTempSourceApi(body: {
    url: string;
}): Promise<any> {
    return await request.post(`/api/v1/channel/manager/crawl`, body);
}

/**
 * GET /api/v1/channel/manager/square
 * 频道广场接口
 * （后端返回结构目前未知，这里先用 any，后续根据实际返回再补类型）
 */
export async function getChannelSquareApi(params?: {
    page?: number;
    page_size?: number;
    [key: string]: any;
}): Promise<any> {
    return await request.get(`/api/v1/channel/manager/square`, { params });
}
