import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { getUserGroupsApi } from "@/controllers/API/user";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function FilterByUsergroup({ value, onChange }) {
    const { t } = useTranslation()
    const { groups, loadData } = useGroups()


    return <div className="w-[200px] relative">
        <Select onOpenChange={loadData} value={value} onValueChange={onChange}>
            <SelectTrigger className="w-[200px]">
                <SelectValue placeholder="用户组" />
            </SelectTrigger>
            <SelectContent className="max-w-[200px] break-all">
                <SelectGroup>
                    {groups.map(g => <SelectItem value={g.id} key={g.id}>{g.group_name}</SelectItem>)}
                </SelectGroup>
            </SelectContent>
        </Select>
    </div>
};


const useGroups = () => {
    const [groups, setGroups] = useState([])
    const loadData = () => {
        getUserGroupsApi().then((res: any) => setGroups(res.records))
    }
    return { groups, loadData }
}