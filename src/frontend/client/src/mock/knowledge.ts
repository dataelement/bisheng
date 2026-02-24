import {
    KnowledgeSpace,
    KnowledgeFile,
    FileStatus,
    FileType,
    VisibilityType,
    SpaceRole
} from "~/api/knowledge";

// 模拟知识空间数据
export const mockKnowledgeSpaces: KnowledgeSpace[] = [
    {
        id: "space-1",
        name: "政策信息",
        description: "国家粮食政策与安全标准汇总",
        visibility: VisibilityType.PUBLIC,
        creator: "admin",
        creatorId: "user-1",
        memberCount: 15,
        fileCount: 205,
        totalFileCount: 271,
        role: SpaceRole.CREATOR,
        isPinned: true,
        createdAt: "2026-01-01T10:00:00",
        updatedAt: "2026-01-27T17:17:17",
        tags: ["国际", "粮食", "大豆油", "国际", "小麦"]
    },
    {
        id: "space-2",
        name: "粮食价格与期货市场",
        description: "国内外粮食价格走势与期货市场分析",
        visibility: VisibilityType.PUBLIC,
        creator: "admin",
        creatorId: "user-1",
        memberCount: 8,
        fileCount: 89,
        totalFileCount: 120,
        role: SpaceRole.CREATOR,
        isPinned: false,
        createdAt: "2026-01-05T14:00:00",
        updatedAt: "2026-01-26T12:00:00",
        tags: ["价格", "期货", "市场分析"]
    },
    {
        id: "space-3",
        name: "财政拨告",
        description: "财政补贴与拨款相关文档",
        visibility: VisibilityType.PRIVATE,
        creator: "张三",
        creatorId: "user-2",
        memberCount: 5,
        fileCount: 45,
        totalFileCount: 56,
        role: SpaceRole.ADMIN,
        isPinned: true,
        createdAt: "2026-01-10T11:00:00",
        updatedAt: "2026-01-25T10:20:00",
        tags: ["财政", "补贴"]
    },
    {
        id: "space-4",
        name: "农业科技与创新",
        description: "农业科技创新与智能化发展资料",
        visibility: VisibilityType.PUBLIC,
        creator: "李四",
        creatorId: "user-3",
        memberCount: 23,
        fileCount: 156,
        totalFileCount: 198,
        role: SpaceRole.MEMBER,
        isPinned: false,
        createdAt: "2025-12-15T16:00:00",
        updatedAt: "2026-01-24T14:00:00",
        tags: ["科技", "创新", "智能化"]
    }
];

// 模拟文件数据
export const mockFiles: KnowledgeFile[] = [
    // 文件夹
    {
        id: "file-1",
        name: "食物政策",
        type: FileType.FOLDER,
        tags: [],
        path: "政策信息/食物政策",
        spaceId: "space-1",
        createdAt: "2026-01-20T10:00:00",
        updatedAt: "2026-01-27T17:27:00"
    },
    {
        id: "file-2",
        name: "财务政策",
        type: FileType.FOLDER,
        tags: [],
        path: "政策信息/财务政策",
        spaceId: "space-1",
        createdAt: "2026-01-15T10:00:00",
        updatedAt: "2026-01-27T2026-01-27"
    },
    // 文件
    {
        id: "file-3",
        name: "人力政策",
        type: FileType.FOLDER,
        tags: [],
        path: "政策信息/人力政策",
        spaceId: "space-1",
        createdAt: "2026-01-10T10:00:00",
        updatedAt: "2026-01-27T17:17:17"
    },
    {
        id: "file-4",
        name: "财务政策",
        type: FileType.FOLDER,
        tags: [],
        path: "政策信息/财务政策",
        spaceId: "space-1",
        createdAt: "2026-01-08T10:00:00",
        updatedAt: "2026-01-27T17:17:17"
    },
    {
        id: "file-5",
        name: "人力政策文件.pdf",
        type: FileType.PDF,
        size: 1810022,  // 1.27MB
        status: FileStatus.SUCCESS,
        tags: ["政策", "国际", "政策"],
        path: "政策信息/人力政策文件.pdf",
        spaceId: "space-1",
        createdAt: "2026-01-20T15:00:00",
        updatedAt: "2026-01-27T17:17:17",
        thumbnail: "/thumbnails/pdf.png"
    },
    {
        id: "file-6",
        name: "粮食新闻.doc",
        type: FileType.DOC,
        size: 18105753,  // 17.27MB
        status: FileStatus.SUCCESS,
        tags: ["政策", "大豆油", "政策"],
        path: "政策信息/粮食新闻.doc",
        spaceId: "space-1",
        createdAt: "2026-01-19T14:00:00",
        updatedAt: "2026-01-27T17:17:17"
    },
    {
        id: "file-7",
        name: "政策报告号.jpg",
        type: FileType.JPG,
        size: 143070822,  // 136.27MB
        status: FileStatus.PROCESSING,
        tags: ["政策", "大豆油"],
        path: "政策信息/政策报告号.jpg",
        spaceId: "space-1",
        createdAt: "2026-01-18T13:00:00",
        updatedAt: "2026-01-27T17:17:17",
        thumbnail: "/thumbnails/jpg.png"
    },
    {
        id: "file-8",
        name: "政策报告号.png",
        type: FileType.PNG,
        size: 84549632,  // 80.27MB
        status: FileStatus.SUCCESS,
        tags: ["水果", "政策"],
        path: "政策信息/政策报告号.png",
        spaceId: "space-1",
        createdAt: "2026-01-17T12:00:00",
        updatedAt: "2026-01-27T17:17:17",
        thumbnail: "/thumbnails/png.png"
    }
];

// 格式化文件大小
export function formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + sizes[i];
}

// 获取文件类型图标颜色
export function getFileTypeColor(type: FileType): string {
    switch (type) {
        case FileType.FOLDER:
            return "#165dff";
        case FileType.PDF:
            return "#f53f3f";
        case FileType.DOC:
        case FileType.DOCX:
            return "#165dff";
        case FileType.XLS:
        case FileType.XLSX:
            return "#00b42a";
        case FileType.PPT:
        case FileType.PPTX:
            return "#ff7d00";
        case FileType.JPG:
        case FileType.JPEG:
        case FileType.PNG:
            return "#722ed1";
        default:
            return "#86909c";
    }
}

// 模拟获取知识空间列表
export function getMockKnowledgeSpaces(type: "created" | "joined"): KnowledgeSpace[] {
    return mockKnowledgeSpaces.filter(space =>
        type === "created"
            ? space.role === SpaceRole.CREATOR
            : space.role !== SpaceRole.CREATOR
    );
}

// 模拟获取文件列表
export function getMockFiles(params: {
    spaceId: string;
    parentId?: string;
    search?: string;
    statusFilter?: FileStatus[];
    page?: number;
    pageSize?: number;
}): {
    data: KnowledgeFile[];
    total: number;
} {
    let filtered = mockFiles.filter(f => f.spaceId === params.spaceId);

    // 父文件夹筛选（这里简化处理，实际需要根据 parentId 筛选）
    if (params.parentId) {
        filtered = filtered.filter(f => f.parentId === params.parentId);
    } else {
        // 根目录
        filtered = filtered.filter(f => !f.parentId);
    }

    // 搜索
    if (params.search) {
        const query = params.search.toLowerCase();
        filtered = filtered.filter(f =>
            f.name.toLowerCase().includes(query) ||
            f.tags.some(tag => tag.toLowerCase().includes(query))
        );
    }

    // 状态筛选
    if (params.statusFilter && params.statusFilter.length > 0) {
        filtered = filtered.filter(f =>
            f.type === FileType.FOLDER || // 文件夹始终显示
            (f.status && params.statusFilter!.includes(f.status))
        );
    }

    const page = params.page || 1;
    const pageSize = params.pageSize || 20;
    const start = (page - 1) * pageSize;
    const end = start + pageSize;

    return {
        data: filtered.slice(start, end),
        total: filtered.length
    };
}
