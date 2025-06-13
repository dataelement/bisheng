import { useRef, useState } from "react";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getAuditGroupsApi, getOperationGroupsApi } from "@/controllers/API/log";

export default function FilterByApp({ value, onChange, isAudit }) {
    const { apps, loadApps, searchApp, loadMoreApps } = useApps(isAudit);

    return (
        <div className="w-[200px] relative">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={apps}
                value={value}
                multiple
                placeholder="应用名称"
                onLoad={loadApps}
                onSearch={searchApp}
                onScrollLoad={loadMoreApps}
                onChange={onChange}
            />
        </div>
    );
}

const useApps = (isAudit: boolean) => {
    const [apps, setApps] = useState<any[]>([]);
    const [page, setPage] = useState(1);
    const hasMoreRef = useRef(true);
    const loadLock = useRef(false); // Prevent multiple simultaneous requests
    const keyWordRef = useRef("");

    // Load apps from the API and store in state
    const loadApps = async (name: string) => {
        try {
            loadLock.current = true;
            const res = await (isAudit ? getAuditGroupsApi : getOperationGroupsApi)({ keyword: name, page: 1, page_size: 50 });
            const options = res.data.map((a: any) => ({
                label: a.name,
                value: a.id,
            }));
            keyWordRef.current = name;
            setApps(options);
            setPage(1);
            hasMoreRef.current = res.data.length > 0;

            setTimeout(() => {
                loadLock.current = false;
            }, 500);
        } catch (error) {
            console.error("Error loading apps:", error);
            // Optionally, you can set apps to an empty array or show an error message
        }
    };

    // Load more apps when scrolling
    const loadMoreApps = async () => {
        if (!hasMoreRef.current) return;
        if (loadLock.current) return;
        try {
            const nextPage = page + 1;
            const res = await (isAudit ? getAuditGroupsApi : getOperationGroupsApi)({ keyword: keyWordRef.current, page: nextPage, page_size: 10 });
            const options = res.data.map((a: any) => ({
                label: a.name,
                value: a.id,
            }));
            setApps((prevApps) => [...prevApps, ...options]);
            setPage(nextPage);
            hasMoreRef.current = res.data.length > 0;
        } catch (error) {
            console.error("Error loading more apps:", error);
        }
    };

    return {
        apps,
        loadApps,
        searchApp: loadApps,
        loadMoreApps
    };
};