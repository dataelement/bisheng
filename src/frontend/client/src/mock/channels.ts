import { Channel, ChannelPreview, Article, SortType, ChannelRole } from "~/api/channels";

// 模拟频道数据
export const mockChannels: Channel[] = [
    // 我创建的
    {
        id: "channel-1",
        name: "北京新闻",
        description: "关注北京本地新闻动态",
        creator: "admin",
        creatorId: "user-1",
        subscriberCount: 271,
        articleCount: 45,
        unreadCount: 3,
        role: ChannelRole.CREATOR,
        isPinned: true,
        createdAt: "2026-01-01T10:00:00",
        updatedAt: "2026-01-17T17:17:17",
        subChannels: [
            { id: "sub-1", name: "科技", articleCount: 12 },
            { id: "sub-2", name: "财经", articleCount: 8 },
            { id: "sub-3", name: "总经", articleCount: 15 },
            { id: "sub-4", name: "国际", articleCount: 6 },
            { id: "sub-5", name: "网评", articleCount: 4 }
        ]
    },
    {
        id: "channel-2",
        name: "国际政策",
        description: "全球政治经济动态跟踪",
        creator: "admin",
        creatorId: "user-1",
        subscriberCount: 156,
        articleCount: 32,
        unreadCount: 0,
        role: ChannelRole.CREATOR,
        isPinned: false,
        createdAt: "2026-01-05T14:00:00",
        updatedAt: "2026-01-16T12:00:00",
        subChannels: [
            { id: "sub-6", name: "欧洲", articleCount: 10 },
            { id: "sub-7", name: "美洲", articleCount: 12 },
            { id: "sub-8", name: "亚洲", articleCount: 10 }
        ]
    },
    {
        id: "channel-3",
        name: "AI 科技最新咨询",
        description: "人工智能领域最新资讯和研究成果",
        creator: "admin",
        creatorId: "user-1",
        subscriberCount: 423,
        articleCount: 67,
        unreadCount: 12,
        role: ChannelRole.CREATOR,
        isPinned: false,
        createdAt: "2025-12-20T09:00:00",
        updatedAt: "2026-01-17T15:30:00",
        subChannels: [
            { id: "sub-9", name: "大模型", articleCount: 25 },
            { id: "sub-10", name: "机器学习", articleCount: 22 },
            { id: "sub-11", name: "计算机视觉", articleCount: 20 }
        ]
    },

    // 我关注的
    {
        id: "channel-4",
        name: "可持续发展观察",
        description: "环境保护、绿色发展相关资讯",
        creator: "张三",
        creatorId: "user-2",
        subscriberCount: 89,
        articleCount: 28,
        unreadCount: 5,
        role: ChannelRole.ADMIN,
        isPinned: true,
        createdAt: "2026-01-10T11:00:00",
        updatedAt: "2026-01-17T10:20:00",
        subChannels: [
            { id: "sub-12", name: "能源", articleCount: 10 },
            { id: "sub-13", name: "环保", articleCount: 18 }
        ]
    },
    {
        id: "channel-5",
        name: "税务政策",
        description: "税收政策解读和分析",
        creator: "李四",
        creatorId: "user-3",
        subscriberCount: 134,
        articleCount: 41,
        unreadCount: 0,
        role: ChannelRole.MEMBER,
        isPinned: false,
        createdAt: "2025-12-15T16:00:00",
        updatedAt: "2026-01-15T14:00:00",
        subChannels: []
    },
    {
        id: "channel-6",
        name: "AI 适用的创新应用",
        description: "AI在各行业的创新应用案例",
        creator: "王五",
        creatorId: "user-4",
        subscriberCount: 298,
        articleCount: 53,
        unreadCount: 8,
        role: ChannelRole.MEMBER,
        isPinned: false,
        createdAt: "2025-11-20T13:00:00",
        updatedAt: "2026-01-17T09:00:00",
        subChannels: [
            { id: "sub-14", name: "医疗", articleCount: 15 },
            { id: "sub-15", name: "教育", articleCount: 18 },
            { id: "sub-16", name: "金融", articleCount: 20 }
        ]
    },
    {
        id: "channel-7",
        name: "AI 技术的未来展望",
        description: "探讨人工智能技术发展趋势",
        creator: "赵六",
        creatorId: "user-5",
        subscriberCount: 512,
        articleCount: 78,
        unreadCount: 15,
        role: ChannelRole.MEMBER,
        isPinned: false,
        createdAt: "2025-10-10T10:00:00",
        updatedAt: "2026-01-17T16:45:00",
        subChannels: []
    },
    {
        id: "channel-8",
        name: "时事讲解",
        description: "深度解读当下热点时事",
        creator: "孙七",
        creatorId: "user-6",
        subscriberCount: 367,
        articleCount: 92,
        unreadCount: 20,
        role: ChannelRole.MEMBER,
        isPinned: false,
        createdAt: "2025-09-05T15:00:00",
        updatedAt: "2026-01-17T11:30:00",
        subChannels: [
            { id: "sub-17", name: "政治", articleCount: 30 },
            { id: "sub-18", name: "经济", articleCount: 32 },
            { id: "sub-19", name: "社会", articleCount: 30 }
        ]
    }
];

// 模拟文章数据
export const mockArticles: Article[] = [
    {
        id: "article-1",
        title: `2025年北京PM2.5年均浓度首次低于"30微克"，全年348个"蓝天"为有监测以来最蓝`,
        url: "https://bjrb.example.com/article/001",
        content: `北京市各级机关2026年度考试录用公务员笔试成绩将在2026年1月5日公布，考生可在北京人事考试网中查询。"北京人社"微信公众号1月3日发布提醒称，考生若需查询考试成绩，可使用该笔试准考证号及身份证号进行查询。若有疑问，请拨打北京市人力资源和社会保障局咨询电话12333进行咨询。`,
        sourceName: "北京日报",
        sourceAvatar: "/sources/bjrb.png",
        sourceId: "source-1",
        channelId: "channel-1",
        isRead: false,
        publishedAt: "2026-01-17T17:17:17",
        createdAt: "2026-01-17T17:17:17",
        coverImage: "/articles/cover-1.jpg"
    },
    {
        id: "article-2",
        title: "北京市各级机关2026年度考试录用公务员笔试成绩分格线数线",
        url: "https://bjrb.example.com/article/002",
        content: "北京市各级机关2026年度考试录用公务员笔试成绩将在2026年1月5日公布，考生可在北京人事考试网中查询。",
        sourceName: "北京日报",
        sourceAvatar: "/sources/bjrb.png",
        sourceId: "source-1",
        channelId: "channel-1",
        isRead: false,
        publishedAt: "2026-01-17T17:17:17",
        createdAt: "2026-01-17T17:17:17",
        coverImage: "/articles/cover-2.jpg"
    },
    {
        id: "article-3",
        title: "慎防边全球人工智能创新高地",
        url: "https://xinhuanet.example.com/article/003",
        content: `2026北京人工智能创新发展战略会"火热召开，大会发布了一系列前沿成果、探独创应用，为首都AI产业发展再添新力量。`,
        sourceName: "新华网",
        sourceAvatar: "/sources/xhw.png",
        sourceId: "source-2",
        channelId: "channel-1",
        isRead: false,
        publishedAt: "2026-01-17T15:30:00",
        createdAt: "2026-01-17T15:30:00",
        coverImage: "/articles/cover-3.jpg"
    },
    {
        id: "article-4",
        title: `2025年北京PM2.5年均浓度首次低于"30微克"，全年348个"蓝天"为有监测以来最蓝`,
        url: "https://bjrb.example.com/article/004",
        content: "北京市环境保护局公布，2025年北京PM2.5年均浓度首次低于30微克/立方米，达到29.8微克/立方米，创历史最好水平。全年蓝天数达348天，为有监测以来最多。",
        sourceName: "北京日报",
        sourceAvatar: "/sources/bjrb.png",
        sourceId: "source-1",
        channelId: "channel-1",
        isRead: false,
        publishedAt: "2026-01-17T10:20:00",
        createdAt: "2026-01-17T10:20:00",
        coverImage: "/articles/cover-4.jpg"
    },
    {
        id: "article-5",
        title: "北京市各级机关2026年度考试录用公务员笔试成绩分格线数线",
        url: "https://bjrb.example.com/article/005",
        content: "考试成绩将在1月5日公布，考生可登录北京人事考试网查询。",
        sourceName: "北京日报",
        sourceAvatar: "/sources/bjrb.png",
        sourceId: "source-1",
        channelId: "channel-1",
        isRead: true,
        publishedAt: "2026-01-05T08:24:00",
        createdAt: "2026-01-05T08:24:00",
        coverImage: "/articles/cover-5.jpg"
    },
    {
        id: "article-6",
        title: "AI技术助力北京智慧城市建设",
        url: "https://kjrb.example.com/article/006",
        content: "北京市加大人工智能技术在城市管理中的应用，推动智慧城市建设迈上新台阶。",
        sourceName: "科技日报",
        sourceAvatar: "/sources/kjrb.png",
        sourceId: "source-3",
        channelId: "channel-1",
        subChannelId: "sub-1",
        isRead: true,
        publishedAt: "2026-01-03T14:30:00",
        createdAt: "2026-01-03T14:30:00"
    }
];

// 模拟信息源数据
export const mockSources = [
    { id: "source-1", name: "北京日报", avatar: "/sources/bjrb.png" },
    { id: "source-2", name: "新华网", avatar: "/sources/xhw.png" },
    { id: "source-3", name: "科技日报", avatar: "/sources/kjrb.png" },
    { id: "source-4", name: "人民网", avatar: "/sources/rmw.png" }
];

// 模拟获取频道列表
export function getMockChannels(params: {
    type: "created" | "subscribed";
    sortBy?: SortType;
}): Channel[] {
    let channels = params.type === "created"
        ? mockChannels.filter(c => c.role === ChannelRole.CREATOR)
        : mockChannels.filter(c => c.role !== ChannelRole.CREATOR);

    // 排序
    if (params.sortBy) {
        channels = sortChannels(channels, params.sortBy);
    }

    return channels;
}

// 排序频道
function sortChannels(channels: Channel[], sortBy: SortType): Channel[] {
    // 先分离置顶和非置顶
    const pinned = channels.filter(c => c.isPinned);
    const unpinned = channels.filter(c => !c.isPinned);

    // 分别排序
    const sortedPinned = applySorting(pinned, sortBy);
    const sortedUnpinned = applySorting(unpinned, sortBy);

    return [...sortedPinned, ...sortedUnpinned];
}

function applySorting(channels: Channel[], sortBy: SortType): Channel[] {
    return [...channels].sort((a, b) => {
        switch (sortBy) {
            case SortType.RECENT_UPDATE:
                return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
            case SortType.RECENT_ADDED:
                return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
            case SortType.NAME:
                return a.name.localeCompare(b.name, 'zh-CN');
            default:
                return 0;
        }
    });
}

// 模拟获取文章列表
export function getMockArticles(params: {
    channelId: string;
    subChannelId?: string;
    search?: string;
    sourceIds?: string[];
    onlyUnread?: boolean;
    page?: number;
    pageSize?: number;
}): {
    data: Article[];
    total: number;
    hasMore: boolean;
} {
    let filtered = mockArticles.filter(a => a.channelId === params.channelId);

    // 子频道筛选
    if (params.subChannelId) {
        filtered = filtered.filter(a => a.subChannelId === params.subChannelId);
    }

    // 搜索
    if (params.search) {
        const query = params.search.toLowerCase();
        filtered = filtered.filter(a =>
            a.title.toLowerCase().includes(query) ||
            a.content.toLowerCase().includes(query) ||
            a.sourceName.toLowerCase().includes(query)
        );
    }

    // 信息源筛选
    if (params.sourceIds && params.sourceIds.length > 0) {
        filtered = filtered.filter(a => params.sourceIds!.includes(a.sourceId));
    }

    // 仅看未读
    if (params.onlyUnread) {
        filtered = filtered.filter(a => !a.isRead);
    }

    // 按时间倒序排列
    filtered.sort((a, b) =>
        new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
    );

    const page = params.page || 1;
    const pageSize = params.pageSize || 6;
    const start = (page - 1) * pageSize;
    const end = start + pageSize;

    return {
        data: filtered.slice(start, end),
        total: filtered.length,
        hasMore: end < filtered.length
    };
}

// 模拟获取频道预览信息
export function getMockChannelPreview(channelId: string): ChannelPreview {
    // 模拟「已删除」的频道
    if (channelId === "deleted-channel") {
        return {
            id: channelId,
            name: "",
            articleCount: 0,
            subscriberCount: 0,
            sources: [],
            articles: [],
            isSubscribed: false,
            needsApproval: false,
            isPending: false,
            isDeleted: true,
            creator: "",
        };
    }

    const channel = mockChannels.find(c => c.id === channelId);
    if (!channel) {
        // 找不到的频道也视为已删除
        return {
            id: channelId,
            name: "",
            articleCount: 0,
            subscriberCount: 0,
            sources: [],
            articles: [],
            isSubscribed: false,
            needsApproval: false,
            isPending: false,
            isDeleted: true,
            creator: "",
        };
    }

    const articles = mockArticles.filter(a => a.channelId === channelId);

    // 模拟不同频道的状态
    // channel-4: 需要审批
    // channel-5: 已订阅
    // channel-8: 申请中
    const needsApproval = channelId === "channel-4";
    const isSubscribed = channelId === "channel-5";
    const isPending = channelId === "channel-8";

    return {
        id: channel.id,
        name: channel.name,
        description: channel.description,
        creator: channel.creator,
        creatorAvatar: "/avatars/user1.png",
        articleCount: channel.articleCount,
        subscriberCount: channel.subscriberCount,
        sources: mockSources.slice(0, 3),
        articles,
        isSubscribed,
        needsApproval,
        isPending,
        isDeleted: false,
    };
}
