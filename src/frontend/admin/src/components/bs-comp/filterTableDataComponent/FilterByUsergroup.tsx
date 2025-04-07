import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { getUserGroupsApi } from "@/controllers/API/user";
import { useCallback, useEffect, useRef, useState } from "react";

interface Group {
    id: string;
    group_name: string;
}

export default function FilterByUsergroup({ value, onChange }) {
    const { groups, loading } = useGroups();

    return (
        <div className="w-[200px] relative">
            <Select value={value} onValueChange={onChange} disabled={loading}>
                <SelectTrigger className="w-[200px]">
                    {value ? (
                        <span>{groups.find(g => g.id === value)?.group_name}</span>
                    ) : (
                        <SelectValue placeholder="用户组" />
                    )}
                </SelectTrigger>
                <SelectContent className="max-w-[200px] break-all">
                    <SelectGroup>
                        {groups.map(g => (
                            <SelectItem
                                value={g.id}
                                key={g.id}
                                className="truncate max-w-[180px]"
                            >
                                {g.group_name}
                            </SelectItem>
                        ))}
                        {!loading && groups.length === 0 && (
                            <div className="text-gray-400 text-sm px-2 py-1">
                                列表是空的
                            </div>
                        )}
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
    );
};

const useGroups = () => {
    const [groups, setGroups] = useState<Group[]>([]);
    const [loading, setLoading] = useState(true);
    const abortControllerRef = useRef<AbortController>();

    const loadData = useCallback(async () => {
        abortControllerRef.current?.abort();
        abortControllerRef.current = new AbortController();

        setLoading(true);
        try {
            const res = await getUserGroupsApi({
                signal: abortControllerRef.current.signal
            });
            setGroups(res.records || []);
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('Failed to load user groups:', error);
            }
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadData();
        return () => abortControllerRef.current?.abort();
    }, [loadData]);

    return { groups, loading, loadData };
};