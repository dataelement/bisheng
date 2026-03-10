import request from "./request";

// 排序方式
export enum SortType {
    RECENT_UPDATE = "latest_update",    // 最近更新
    RECENT_ADDED = "latest_added",      // 最近添加
    NAME = "channel_name"               // 频道名称
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
    source_list?: string[];    // 信息源 ID 列表（后端返回）
}

// 文章接口（前端展示用，兼容旧字段）
export interface Article {
    id: string;
    title: string;
    url: string;               // 原文链接
    content: string;           // 正文（纯文本）
    content_html?: string;     // HTML 内容
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
    highlight?: Record<string, string[]>;  // 搜索高亮
    source_type?: number;      // 信源类型: 0-公众号 1-网站
}

// Backend article search result item
export interface ArticleSearchResultItem {
    doc_id: string;
    source_type: number;       // 0-公众号 1-网站
    source_id: string;
    title: string;
    content: string;           // May contain HTML markup
    content_html: string;      // Full HTML content
    cover_image?: string;
    publish_time?: string;
    source_url?: string;
    create_time?: string;
    update_time?: string;
    score?: number;
    highlight?: Record<string, string[]>;
    is_read?: boolean;
    source_info?: {
        id: string;
        source_name: string;
        source_icon: string;
        source_type: string;
        description?: string;
    };
}

// 后端文章搜索分页响应
export interface ArticleSearchPageResponse {
    data: ArticleSearchResultItem[];
    total: number;
    page: number;
    page_size: number;
}

export interface ChannelItemResponse {
    id: string;
    name: string;
    source_list: string[];
    visibility: "public" | "private" | "review";
    is_released: boolean;
    latest_article_update_time?: string;
    create_time?: string;
    user_role: "creator" | "admin" | "member";
    is_pinned: boolean;
    subscribed_at?: string;
    unread_count?: number;
}

// Channel detail response from GET /api/v1/channel/manager/{channel_id}
export interface ChannelDetailResponse {
    id: string;
    name: string;
    description?: string;
    source_list: string[];
    visibility: "public" | "private" | "review";
    is_released: boolean;
    latest_article_update_time?: string;
    create_time?: string;
    creator_name: string;
    subscriber_count: number;
    article_count: number;
    filter_rules?: Array<{
        rules: Array<{ rule_type: string; keywords: string[]; relation: string }>;
        channel_type: "main" | "sub";
        name?: string;
    }>;
}

/**
 * 获取频道列表
 */
export async function getChannelsApi(params: {
    type: "created" | "subscribed";  // 我创建的 / 我关注的
    sortBy?: SortType;
}): Promise<Channel[]> {
    const query_type = params.type === "subscribed" ? "followed" : params.type;
    const res: any = await request.get(`/api/v1/channel/manager/my_channels`, {
        params: {
            query_type,
            sort_by: params.sortBy || SortType.RECENT_UPDATE
        }
    });
    // map ChannelItemResponse to Channel for now to minimize refactoring, 
    // or modify types later. Since we are just checking interface returns, returning raw or mapped data.
    // Assuming backend returns an unwrapped array or wrapped in data. We will map to matched fields.
    const data = res.data || res;
    return (Array.isArray(data) ? data : []).map((item: any) => ({
        id: item.id,
        name: item.name,
        creator: "",
        creatorId: "",
        subscriberCount: 0,
        articleCount: 0,
        unreadCount: item.unread_count || 0,
        role: item.user_role as ChannelRole,
        isPinned: item.is_pinned,
        createdAt: item.create_time,
        updatedAt: item.latest_article_update_time || item.update_time,
        subChannels: [],
        ...item,
    }));
}

/**
 * 创建频道
 */
export async function createChannelApi(data: {
    name: string;
    description?: string;
    subChannels?: string[];
}): Promise<Channel> {
    return await request.post(`/api/v1/channels`, data);
}

/**
 * 更新频道信息
 * PUT /api/v1/channel/manager/{channel_id}
 */
export async function updateChannelApi(
    channelId: string,
    data: any
): Promise<any> {
    const res: any = await request.put(`/api/v1/channel/manager/${channelId}`, data);
    return res?.data ?? res;
}

/**
 * 订阅频道
 */
export async function subscribeChannelApi(channelId: string): Promise<void> {
    return await request.post(`/api/v1/channels/${channelId}/subscribe`);
}

/**
 * 取消订阅频道
 * POST /api/v1/channel/manager/{channel_id}/unsubscribe
 */
export async function unsubscribeChannelApi(channelId: string): Promise<any> {
    const res: any = await request.post(`/api/v1/channel/manager/${channelId}/unsubscribe`);
    return res?.data ?? res;
}

/**
 * 解散频道
 * DELETE /api/v1/channel/manager/{channel_id}
 */
export async function deleteChannelApi(channelId: string): Promise<any> {
    const res: any = await request.delete(`/api/v1/channel/manager/${channelId}`);
    return res?.data ?? res;
}

/**
 * 置顶/取消置顶频道
 * POST /api/v1/channel/manager/set_pin
 */
export async function pinChannelApi(channelId: string, pinned: boolean): Promise<any> {
    const res: any = await request.post(`/api/v1/channel/manager/set_pin`, {
        channel_id: channelId,
        is_pinned: pinned
    });
    return res?.data ?? res;
}

/**
 * 获取频道文章列表
 * GET /api/v1/channel/manager/articles
 */
export async function getArticlesApi(params: {
    channelId: string;
    subChannelName?: string;   // Sub-channel name
    keyword?: string;          // Search keyword
    sourceIds?: string[];      // Source ID list
    onlyUnread?: boolean;      // Only show unread articles
    page?: number;
    pageSize?: number;
}): Promise<ArticleSearchPageResponse> {
    const res: any = await request.get(`/api/v1/channel/manager/articles`, {
        params: {
            channel_id: params.channelId,
            keyword: params.keyword || undefined,
            source_ids: params.sourceIds?.length ? params.sourceIds.join(',') : undefined,
            sub_channel_name: params.subChannelName || undefined,
            only_unread: params.onlyUnread || undefined,
            page: params.page || 1,
            page_size: params.pageSize || 20,
        }
    });
    return res?.data ?? res;
}

/**
 * 获取文章详情
 * GET /api/v1/channel/manager/articles/detail/{article_id}
 */
export async function getArticleDetailApi(articleId: string): Promise<ArticleSearchResultItem> {
    const res: any = await request.get(`/api/v1/channel/manager/articles/detail/${articleId}`);
    return res?.data ?? res;
}

/**
 * 获取频道详情
 * GET /api/v1/channel/manager/{channel_id}
 */
export async function getChannelDetailApi(channelId: string): Promise<ChannelDetailResponse> {
    const res: any = await request.get(`/api/v1/channel/manager/${channelId}`);
    return res?.data ?? res;
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
    source_id?: string;
    name: string;
    icon?: string;
    original_url?: string;
    description?: string | null;
    follow_num?: number;
    business_type: ChannelBusinessType;
}

// 单条筛选规则
export interface ManagerChannelRuleItem {
    rule_type?: string;        // 规则类型，例如 include / exclude 等
    keywords?: string[];       // 关键词列表
    relation?: string;         // and / or，规则内部关系
}

// 一组条件 + 关系
export interface ManagerChannelFilterRule {
    rules?: ManagerChannelRuleItem[];
    relation?: string;         // 预留（目前后端示例不用）
    channel_type?: "main" | "sub"; // 频道类型：主频道 / 子频道
    name?: string;                 // 分组名称（例如子频道名称）
}

// 创建频道（manager）接口入参
export interface CreateManagerChannelPayload {
    name: string;                         // 频道名称（必填）
    description?: string | null;          // 频道简介（可选）
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
    sources: ManagerSource[];
    total: number;
}> {
    const res: any = await request.get(`/api/v1/channel/manager/list_sources`, { params });
    const root = res?.data ?? res;
    const payload = root?.data ?? root;
    return {
        sources: payload?.sources ?? [],
        total: payload?.total ?? 0
    };
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
    keyword?: string;
    page?: number;
    page_size?: number;
}): Promise<any> {
    return await request.get(`/api/v1/channel/manager/square`, { params });
}

/**
 * POST /api/v1/channel/manager/subscribe
 * 订阅频道申请
 */
export async function subscribeManagerChannelApi(body: {
    channel_id: string;
}): Promise<any> {
    return await request.post(`/api/v1/channel/manager/subscribe`, body);
}

// 频道成员
export interface ChannelMember {
    user_id: number;
    user_name: string;
    avatar?: string;
    role: "creator" | "admin" | "member";
    groups?: string[];
}

/**
 * GET /api/v1/channel/manager/members
 * 查询频道成员
 */
export async function getChannelMembersApi(params: {
    channel_id: string;
    keyword?: string;
    page?: number;
    page_size?: number;
}): Promise<{
    data: ChannelMember[];
    total: number;
}> {
    const res: any = await request.get(`/api/v1/channel/manager/members`, { params });
    // 标准返回: { status_code, status_message, data: { data: [], total } }
    const payload = res?.status_code ? res.data : (res?.data ?? res);
    return {
        data: (payload?.data ?? payload?.members ?? []).map((m: any) => ({
            user_id: Number(m.user_id),
            user_name: String(m.user_name ?? ""),
            avatar: m.avatar ?? m.icon,
            role: (m.user_role ?? m.role ?? "member") as ChannelMember["role"],
            groups: (m.user_groups ?? m.groups ?? []).map((g: any) => String(g.name ?? g)).filter(Boolean)
        })),
        total: payload?.total ?? 0
    };
}

/**
 * POST /api/v1/channel/manager/update_member_role
 * 设置成员角色（管理员 / 普通成员）
 */
export async function updateChannelMemberRoleApi(body: {
    channel_id: string;
    user_id: number;
    role: "admin" | "member";
}): Promise<any> {
    return await request.post(`/api/v1/channel/manager/update_member_role`, body);
}

/**
 * POST /api/v1/channel/manager/remove_member
 * 移除频道成员
 */
export async function removeChannelMemberApi(body: {
    channel_id: string;
    user_id: number;
}): Promise<any> {
    return await request.post(`/api/v1/channel/manager/remove_member`, body);
}

// ── Information Source types (migrated from ~/mock/sources) ──

/** Source type */
export type SourceType = "official_account" | "website";

/** Information source entity */
export interface InformationSource {
    id: string;
    name: string;
    avatar?: string;
    type: SourceType;
    url?: string;
}

/** Truncate name with ellipsis */
export function truncateName(name: string, max = 20): string {
    if (name.length <= max) return name;
    return name.slice(0, max) + "...";
}

