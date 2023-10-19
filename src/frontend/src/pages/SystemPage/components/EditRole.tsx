import { useContext, useEffect, useRef, useState } from "react";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/ui/table";
import { Switch } from "../../../components/ui/switch";
import { useDebounce } from "../../../util/hook";
import { Search } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { alertContext } from "../../../contexts/alertContext";

const SearchPanne = ({ title, onChange, children }) => {
    const [page, setPage] = useState(1)
    const searchKeyRef = useRef('')

    const handleSearch = useDebounce((e) => {
        searchKeyRef.current = e.target.value
        setPage(1)
        onChange(1, searchKeyRef.current)
    }, 500, false)

    const loadPage = (page) => {
        setPage(page)
        onChange(page, searchKeyRef.current)
    }

    return <>
        <div className="mt-20 flex justify-between items-center relative">
            <p className="font-bold">{title}</p>
            <Input className="w-[300px] rounded-full" onChange={handleSearch}></Input>
            <Search className="absolute right-2" color="#999" />
        </div>
        <div className="mt-4">
            {children}
        </div>
        <div className="join grid grid-cols-2 w-[200px] mx-auto my-4">
            <button disabled={page === 1} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page - 1)}>上一页</button>
            <button disabled={page >= 100} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page + 1)}>下一页</button>
        </div>
    </>

}



export default function EditRole({ id, onChange }) {
    const { setErrorData, setSuccessData } = useContext(alertContext);

    const [form, setForm] = useState({
        name: '',
        useSkills: [],
        useLibs: [],
        manageLibs: []
    })
    useEffect(() => {
        if (id !== -1) {
            // 获取详情
            // setForm()
        }
    }, [id])

    const skillSwitchChange = (checked, id) => {
        const index = form.useSkills.findIndex(el => el === id)
        checked && index === -1 && form.useSkills.push(id)
        !checked && index !== -1 && form.useSkills.splice(index, 1)
        setForm({ ...form, useSkills: form.useSkills })
    }

    const { data: skills, change: handleSkillChange } = usePageData('skill') // TODO 每页十个
    const { data: Libs, change: handleLibChange } = usePageData('lib')

    const handleSave = () => {
        if (form.name.length > 50) {
            return setErrorData({
                title: "提示",
                list: ['角色名称不能超过50字符'],
            });
        }
        console.log('form :>> ', form);
        onChange(true)
    }

    return <div className="max-w-[600px] mx-auto pt-4">
        <div className="font-bold mt-4">
            <p className="mb-4">角色名称</p>
            <Input placeholder="角色名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={60}></Input>
        </div>
        <div className="">
            <SearchPanne title='技能授权' onChange={handleSkillChange}>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">技能名称</TableHead>
                            <TableHead>创建人</TableHead>
                            <TableHead className="text-right">使用权限</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {skills.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">{el.name}</TableCell>
                                <TableCell>{el.user}</TableCell>
                                <TableCell className="text-right">
                                    <Switch checked={form.useSkills.includes(el.id)} onCheckedChange={(bln) => skillSwitchChange(bln, el.id)} />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </SearchPanne>
        </div>
        <div className="">
            <SearchPanne title='知识库授权' onChange={handleLibChange}>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">技能名称</TableHead>
                            <TableHead>创建人</TableHead>
                            <TableHead className="text-right">使用权限</TableHead>
                            <TableHead className="text-right">管理权限</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {Libs.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">{el.name}</TableCell>
                                <TableCell>{el.user}</TableCell>
                                <TableCell className="text-right">
                                    <Switch checked={false} onCheckedChange={() => { }} />
                                </TableCell>
                                <TableCell className="text-right">
                                    <Switch checked={false} onCheckedChange={() => { }} />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </SearchPanne>
        </div>
        <div className="flex justify-center gap-4 mt-16">
            <Button variant="outline" className="h-8 rounded-full px-16" onClick={() => onChange()}>取消</Button>
            <Button className="h-8 rounded-full px-16" onClick={handleSave}>保存</Button>
        </div>
    </div>

}


const usePageData = (key: string) => {
    const [data, setData] = useState([{ id: 1, name: 'xxx', user: 'xxxx' }, { id: 2, name: 'xxx', user: 'xxxx' }, { id: 3, name: 'xxx', user: 'xxxx' }])
    const change = (page, keyword) => {
        setData([{ id: 4, name: 'xxx', user: 'xxxx' }])
    }

    return {
        data,
        change
    }
}