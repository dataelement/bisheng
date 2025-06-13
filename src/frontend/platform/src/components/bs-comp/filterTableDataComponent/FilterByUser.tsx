
import { useRef, useState } from "react";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getUsersApiForUser } from "@/controllers/API/user";

export default function FilterByUser({ value, onChange, isAudit }) {
    const { users, loadUsers, searchUser, loadMoreUsers } = useUsers(isAudit);

    return (
        <div className="w-[200px] relative">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={users}
                value={value}
                placeholder="用户名"
                onLoad={loadUsers}
                onSearch={searchUser}
                onScrollLoad={loadMoreUsers}
                onChange={onChange}
            />
        </div>
    );
}

const useUsers = (isAudit: boolean) => {
    const [users, setUsers] = useState<any[]>([]);
    const [page, setPage] = useState(1);
    const hasMoreRef = useRef(true);
    const loadLock = useRef(false); // Prevent multiple simultaneous requests
    const keyWordRef = useRef("");

    // Load users from the API and store in state
    const loadUsers = async (name: string) => {
        try {
            const res = await getUsersApiForUser({ name, page: 1, pageSize: 50, isAudit });
            const options = res.data.map((u: any) => ({
                label: u.user_name,
                value: u.user_id,
            }));
            keyWordRef.current = name;
            setUsers(options);
            setPage(1);
            hasMoreRef.current = res.data.length > 0;

            setTimeout(() => {
                loadLock.current = false;
            }, 500);
        } catch (error) {
            console.error("Error loading users:", error);
            // Optionally, you can set users to an empty array or show an error message
        }
    };

    // Load more apps when scrolling
    const loadMoreUsers = async () => {
        if (!hasMoreRef.current) return;
        if (loadLock.current) return;
        try {
            const nextPage = page + 1;
            const res = await getUsersApiForUser({ name: keyWordRef.current, page: nextPage, pageSize: 50, isAudit });
            const options = res.data.map((a: any) => ({
                label: a.user_name,
                value: a.user_id,
            }));
            setUsers((prevApps) => [...prevApps, ...options]);
            setPage(nextPage);
            hasMoreRef.current = res.data.length > 0;
        } catch (error) {
            console.error("Error loading more apps:", error);
        }
    };

    return {
        users,
        loadUsers,
        searchUser: loadUsers,
        loadMoreUsers
    };
};
