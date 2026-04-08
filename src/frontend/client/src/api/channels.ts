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
