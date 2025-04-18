import MultiSelect from "@/components/bs-ui/select/multi";
import { getUsersApi } from "@/controllers/API/user";
import { debounce } from "lodash";
import { useCallback, useEffect, useRef, useState } from "react";

interface UserOption {
    label: string;
    value: string;
}

export default function FilterByUser({ value, onChange }) {
    const { users, loadUsers, searchUser, loadMoreUsers } = useUsers();

    return (
        <div className="w-[200px] relative">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={users}
                value={value}
                placeholder="用户名"
                onLoad={() => loadUsers("")}
                onSearch={searchUser}
                onScrollLoad={loadMoreUsers}
                onChange={onChange}
            />
        </div>
    );
}

const useUsers = () => {
    const [users, setUsers] = useState<UserOption[]>([]);
    const pageRef = useRef(1);
    const hasMoreRef = useRef(true);
    const loadLock = useRef(false);
    const keywordRef = useRef("");
    const abortControllerRef = useRef<AbortController>();

    // 通用数据映射
    const mapUserData = (data: any[]): UserOption[] =>
        data.map(u => ({ label: u.user_name, value: u.user_id }));

    // 统一请求处理
    const fetchUsers = async (params: {
        name: string;
        page: number;
        pageSize: number
    }) => {
        abortControllerRef.current?.abort();
        abortControllerRef.current = new AbortController();

        try {
            const res = await getUsersApi(
                {
                    name: params.name,
                    page: params.page,
                    pageSize: params.pageSize
                },
                { signal: abortControllerRef.current.signal }
            );
            return res.data;
        } catch (error) {
            if (error.name === 'AbortError') return [];
            throw error;
        }
    };

    // 加载用户（初始/搜索）
    const loadUsers = useCallback(async (name: string) => {
        if (loadLock.current) return;

        loadLock.current = true;
        keywordRef.current = name;

        try {
            const data = await fetchUsers({
                name,
                page: 1,
                pageSize: 20  // 统一分页大小
            });

            setUsers(mapUserData(data));
            pageRef.current = 1;
            hasMoreRef.current = data.length === 20;
        } catch (error) {
            console.error("用户加载失败:", error);
        } finally {
            loadLock.current = false;
        }
    }, []);

    // 滚动加载更多
    const loadMoreUsers = useCallback(async () => {
        if (!hasMoreRef.current || loadLock.current) return;

        loadLock.current = true;

        try {
            const nextPage = pageRef.current + 1;
            const data = await fetchUsers({
                name: keywordRef.current,
                page: nextPage,
                pageSize: 20
            });

            setUsers(prev => [...prev, ...mapUserData(data)]);
            pageRef.current = nextPage;
            hasMoreRef.current = data.length === 20;
        } catch (error) {
            console.error("加载更多用户失败:", error);
        } finally {
            loadLock.current = false;
        }
    }, []);

    // 防抖搜索
    const searchUser = useCallback(
        debounce((name: string) => loadUsers(name), 500),
        [loadUsers]
    );

    // 组件卸载时取消请求
    useEffect(() => {
        return () => abortControllerRef.current?.abort();
    }, []);

    return {
        users,
        loadUsers,
        searchUser,
        loadMoreUsers
    };
};