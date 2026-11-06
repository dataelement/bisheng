// @ts-strict-ignore
import { Select } from "@bisheng/ui";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { getUserGroupsApi } from "@/controllers/API/user";
import { useCallback, useEffect, useRef, useState } from "react";

interface Group {
    id: string;
    group_name: string;
    placeholder?: string;
}

export default function FilterByUsergroup({ value, placeholder = '', onChange }) {
    const selectLabels = useSelectLabels();
    const { groups, loading } = useGroups();

    return (
        <Select
            {...selectLabels}
            allowClear
            className="w-[200px]"
            aria-label={placeholder}
            placeholder={placeholder}
            disabled={loading}
            value={value || null}
            onChange={(v) => onChange(v == null ? '' : v)}
            options={groups
                .filter(g => g.id != null && g.id !== '')
                .map(g => ({ value: g.id, label: g.group_name }))}
        />
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
            setGroups(res || []);
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