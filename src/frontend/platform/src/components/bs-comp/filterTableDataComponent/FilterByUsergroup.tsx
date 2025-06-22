// 业务组件 用于审计运营页的用户组选择
import MultiSelect from "@/components/bs-ui/select/multi";
import { getAuditGroupsApi, getOperationGroupsApi } from "@/controllers/API/user";
import { useEffect, useRef, useState } from "react";
import SelectGroup from "@/components/bs-comp/selectGroup";
import { useQuery } from "react-query";
import { buildUserGroupTreeOptimized } from "@/util/utils";

// 0623 此组件改为树形
export default function FilterByUsergroup({ value, onChange, isAudit }) {
    const { apps, loadData, searchData, loadMoreGroups } = useGroups(isAudit);
    const options = apps;
    useEffect(() => {
        loadData();
    }, [])
    // 这两行为了兼容旧逻辑
    const newValue = value?.length ? { id: value[0].value, group_name: value[0].label } : undefined;
    const newOnchange = (value) => {
        const newValue = value ? [{
            value: value.id,
            label: value.group_name,
        }] :  [];
        return onChange(newValue)
    }
    return  <div className="w-[240px] relative">
        <SelectGroup
            disabled={false}
            value={newValue}
            onChange={newOnchange}
            options={options}
            showSearch
            contentClassName="overflow-y-auto max-w-[240px]"
            handleSearch={(e) => {
                console.log('e', e.target.value)
                loadData(e.target.value || '')
            }}
            searchPlaceholder={'用户组'}
        />
    </div>;
    return (
        <div className="w-[200px] relative">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={apps}
                value={value}
                placeholder="用户组"
                onLoad={loadData}
                onSearch={searchData}
                onScrollLoad={loadMoreGroups}
                onChange={onChange}
            />
        </div>
    );
}

const useGroups = (isAudit: boolean) => {
    const [apps, setApps] = useState<any[]>([]);
    const [page, setPage] = useState(1);
    const hasMoreRef = useRef(true);
    const loadLock = useRef(false); // Prevent multiple simultaneous requests
    const keyWordRef = useRef("");

    // Load apps from the API and store in state
    const loadData = async (name: string = '') => {
        try {
            loadLock.current = true;
            const res = await (isAudit ? getAuditGroupsApi : getOperationGroupsApi)({ keyword: name, page: 1, page_size: 5000 });
            const options = buildUserGroupTreeOptimized(res.data);
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
    const loadMoreGroups = async () => {
        if (!hasMoreRef.current) return;
        if (loadLock.current) return;
        try {
            const nextPage = page + 1;
            const res = await (isAudit ? getAuditGroupsApi : getOperationGroupsApi)({ keyword: keyWordRef.current, page: nextPage, page_size: 10 });
            const options = res.data.map((a: any) => ({
                label: a.group_name,
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
        loadData,
        searchData: loadData,
        loadMoreGroups
    };
};