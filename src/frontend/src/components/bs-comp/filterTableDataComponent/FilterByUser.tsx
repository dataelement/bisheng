import MultiSelect from "@/components/bs-ui/select/multi";
import { getOperatorsApi } from "@/controllers/API/log";
import { useState, useRef } from "react";

export default function FilterByUser({ value, onChange }) {
    const { users, loadUsers, searchUser } = useUsers();

    return (
        <div className="w-[200px] relative">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={users}
                value={value}
                placeholder="用户名"
                onLoad={loadUsers}
                onSearch={searchUser}
                onChange={onChange}
            />
        </div>
    );
}

const useUsers = () => {
    const [users, setUsers] = useState<any[]>([]);
    const userRef = useRef<any[]>([]);
    const selectedRef = useRef<any[]>([]);

    // Load users from the API and store in state
    const loadUsers = async () => {
        try {
            const res = await getOperatorsApi();
            const options = res.map((u: any) => ({
                label: u.user_name,
                value: u.user_id,
            }));
            userRef.current = options;
            setUsers(options);
        } catch (error) {
            console.error("Error loading users:", error);
            // Optionally, you can set users to an empty array or show an error message
        }
    };

    // Search users from the API
    const searchUser = async (name: string) => {
        try {
            const res = await getOperatorsApi({ keyword: name });
            const options = res.map((u: any) => ({
                label: u.user_name,
                value: u.user_id,
            }));
            userRef.current = options;
            setUsers(options);
        } catch (error) {
            console.error("Error searching users:", error);
            // Optionally, handle the error by clearing the list or showing a message
        }
    };

    return {
        users,
        loadUsers,
        searchUser,
    };
};
