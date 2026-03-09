/** 信息源类型 */
export type SourceType = "official_account" | "website";

/** 信息源 */
export interface InformationSource {
    id: string;
    name: string;
    avatar?: string;
    type: SourceType;
    url?: string; // 网站专属
}

/** 公众号列表（模拟数据） */
export const mockOfficialAccounts: InformationSource[] = [
    { id: "oa-1", name: "量子位", avatar: "/sources/quantum.png", type: "official_account" },
    { id: "oa-2", name: "远川研究所", avatar: "/sources/yuanchuan.png", type: "official_account" },
    { id: "oa-3", name: "北京日报", avatar: "/sources/bjrb.png", type: "official_account" },
    { id: "oa-4", name: "新华网", avatar: "/sources/xhw.png", type: "official_account" },
    { id: "oa-5", name: "科技日报", avatar: "/sources/kjrb.png", type: "official_account" },
    { id: "oa-6", name: "人民网", avatar: "/sources/rmw.png", type: "official_account" },
    { id: "oa-7", name: "人民日报", avatar: "/sources/rmrb.png", type: "official_account" },
    { id: "oa-8", name: "央视新闻", avatar: "/sources/ysxw.png", type: "official_account" },
    { id: "oa-9", name: "第一财经", avatar: "/sources/dycj.png", type: "official_account" },
    { id: "oa-10", name: "36氪", avatar: "/sources/36kr.png", type: "official_account" }
];

/** 网站列表（模拟数据） */
export const mockWebsites: InformationSource[] = [
    { id: "web-1", name: "新浪科技", avatar: "/sources/sina.png", type: "website", url: "https://tech.sina.com.cn" },
    { id: "web-2", name: "网易科技", avatar: "/sources/163.png", type: "website", url: "https://tech.163.com" },
    { id: "web-3", name: "搜狐新闻", avatar: "/sources/sohu.png", type: "website", url: "https://news.sohu.com" },
    { id: "web-4", name: "澎湃新闻", avatar: "/sources/thepaper.png", type: "website", url: "https://www.thepaper.cn" },
    { id: "web-5", name: "界面新闻", avatar: "/sources/jiemian.png", type: "website", url: "https://www.jiemian.com" },
    { id: "web-6", name: "虎嗅网", avatar: "/sources/huxiu.png", type: "website", url: "https://www.huxiu.com" },
    { id: "web-7", name: "钛媒体", avatar: "/sources/tmtpost.png", type: "website", url: "https://www.tmtpost.com" },
    { id: "web-8", name: "亿欧网", avatar: "/sources/iyiou.png", type: "website", url: "https://www.iyiou.com" }
];

/** 截断名称，最多 20 字符 */
export function truncateName(name: string, max = 20): string {
    if (name.length <= max) return name;
    return name.slice(0, max) + "...";
}
