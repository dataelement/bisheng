import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { getUserGroupsApi, getAuditGroupsApi, getOperationGroupsApi} from "@/controllers/API/user";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export default function FilterByUsergroup({ value, onChange, isAudit }) {
    const { t } = useTranslation()
    const { groups, loadData } = useGroups(isAudit)
    return <div className="w-[200px] relative">
        <Select value={value} onValueChange={onChange}>
            <SelectTrigger className="w-[200px]">
                {value ? <span>{groups.find(g => g.id == value)?.group_name}</span> : <SelectValue placeholder="用户组" />}
            </SelectTrigger>
            <SelectContent className="max-w-[200px] break-all">
                <SelectGroup>
                    {groups.map(g => <SelectItem value={g.id} key={g.id}>{g.group_name}</SelectItem>)}
                </SelectGroup>
            </SelectContent>
        </Select>
    </div>
};


const useGroups = (isAudit: boolean) => {
    const [groups, setGroups] = useState([])
    const loadData = async () => {
        const res: any = await (isAudit ? getAuditGroupsApi : getOperationGroupsApi)();
        setGroups(res.records);
    }

    useEffect(() => {
        loadData()
    }, [])
    return { groups, loadData }
}