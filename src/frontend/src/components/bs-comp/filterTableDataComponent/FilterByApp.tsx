import MultiSelect from "@/components/bs-ui/select/multi";
import { getGroupsApi } from "@/controllers/API/log";
import debounce from "lodash-es/debounce";
import { useCallback, useEffect, useRef, useState } from "react";

interface AppOption {
    label: string;
    value: string;
}

export default function FilterByApp({ value, onChange }) {
    const { apps, loadApps, searchApps, loadMoreApps } = useApps();

    return (
        <div className="w-[200px] relative">
            <MultiSelect
                contentClassName="max-w-[200px]"
                options={apps}
                value={value}
                multiple
                placeholder="应用名称"
                onLoad={() => loadApps("")} // 初始加载
                onSearch={searchApps} // 搜索时触发
                onScrollLoad={loadMoreApps} // 滚动加载更多
                onChange={onChange} // 选择项变化时触发
            />
        </div>
    );
}

/**
 * 自定义 Hook：用于管理应用列表的数据加载逻辑
 */
const useApps = () => {
    const [apps, setApps] = useState<AppOption[]>([]); // 应用列表数据
    const pageRef = useRef(1); // 当前页码
    const hasMoreRef = useRef(true); // 是否还有更多数据
    const loadLock = useRef(false); // 加载锁，防止重复请求
    const keywordRef = useRef(""); // 当前搜索关键词
    const abortControllerRef = useRef<AbortController>(); // 用于取消请求

    /**
     * 将 API 返回的数据映射为选项格式
     */
    const mapApiData = (data: any[]): AppOption[] =>
        data.map((item) => ({ label: item.name, value: item.id }));

    /**
     * 发起 API 请求获取数据
     */
    const fetchData = async (params: {
        keyword: string;
        page: number;
        pageSize: number;
    }) => {
        // 取消之前的请求
        abortControllerRef.current?.abort();
        abortControllerRef.current = new AbortController();

        try {
            const res = await getGroupsApi(
                {
                    keyword: params.keyword,
                    page: params.page,
                    page_size: params.pageSize,
                },
                { signal: abortControllerRef.current.signal } // 绑定 AbortController
            );
            return res.data;
        } catch (error) {
            if (error.name === "AbortError") return []; // 忽略取消请求的错误
            throw error; // 抛出其他错误
        }
    };

    /**
     * 加载应用列表（初始加载或搜索）
     */
    const loadApps = useCallback(async (keyword: string) => {
        if (loadLock.current) return; // 如果正在加载，则直接返回

        loadLock.current = true; // 加锁
        keywordRef.current = keyword; // 更新搜索关键词

        try {
            const data = await fetchData({
                keyword,
                page: 1,
                pageSize: 10,
            });

            setApps(mapApiData(data)); // 更新应用列表
            pageRef.current = 1; // 重置页码
            hasMoreRef.current = data.length === 10; // 判断是否还有更多数据
        } catch (error) {
            console.error("加载应用列表失败:", error);
        } finally {
            loadLock.current = false; // 解锁
        }
    }, []);

    /**
     * 加载更多应用（滚动加载）
     */
    const loadMoreApps = useCallback(async () => {
        if (!hasMoreRef.current || loadLock.current) return; // 如果没有更多数据或正在加载，则直接返回

        loadLock.current = true; // 加锁

        try {
            const nextPage = pageRef.current + 1;
            const data = await fetchData({
                keyword: keywordRef.current,
                page: nextPage,
                pageSize: 10,
            });

            setApps((prev) => [...prev, ...mapApiData(data)]); // 追加新数据
            pageRef.current = nextPage; // 更新页码
            hasMoreRef.current = data.length === 10; // 判断是否还有更多数据
        } catch (error) {
            console.error("加载更多应用失败:", error);
        } finally {
            loadLock.current = false; // 解锁
        }
    }, []);

    /**
     * 搜索应用（带防抖）
     */
    const searchApps = useCallback(
        debounce((keyword: string) => loadApps(keyword), 500), // 500ms 防抖
        [loadApps]
    );

    /**
     * 组件卸载时取消未完成的请求
     */
    useEffect(() => {
        return () => abortControllerRef.current?.abort();
    }, []);

    return { apps, loadApps, searchApps, loadMoreApps };
};