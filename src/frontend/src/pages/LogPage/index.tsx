import { Button } from "@/components/bs-ui/button";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import MultiSelect from "@/components/bs-ui/select/multi";
import { useTranslation } from "react-i18next";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import { useEffect, useRef, useState } from "react";
import { getUsersApi } from "@/controllers/API/user";

export default function index() {
    const { t } = useTranslation()
    const { users, reload, loadMore, search } = useUsers()

    return <div className="relative">
        <div className="h-[calc(100vh-98px)] overflow-y-auto px-2 py-4 pb-10">
            <div className="flex flex-wrap gap-4">
                <div className="w-[180px] relative">
                    <MultiSelect
                        className=" w-full"
                        options={users}
                        value={[]}
                        placeholder="选择用户"
                        onLoad={reload}
                        onSearch={search}
                        onScrollLoad={loadMore}
                        onChange={(values) => console.log(values)}
                    ></MultiSelect>
                </div>
                <div className="w-[180px] relative">
                    <Select>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="选择用户组" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="apple">Apple</SelectItem>
                                <SelectItem value="banana">Banana</SelectItem>
                                <SelectItem value="blueberry">Blueberry</SelectItem>
                                <SelectItem value="grapes">Grapes</SelectItem>
                                <SelectItem value="pineapple">Pineapple</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <div className="w-[180px] relative">
                    <Select>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="选择角色" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="apple">Apple</SelectItem>
                                <SelectItem value="banana">Banana</SelectItem>
                                <SelectItem value="blueberry">Blueberry</SelectItem>
                                <SelectItem value="grapes">Grapes</SelectItem>
                                <SelectItem value="pineapple">Pineapple</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <div className="w-[180px] relative">
                    <DatePicker placeholder='开始日期' onChange={(t) => { }} />
                </div>
                <div className="w-[180px] relative">
                    <DatePicker placeholder='结束日期' onChange={(t) => { }} />
                </div>
                <div className="w-[180px] relative">
                    <Select>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="系统模块" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="apple">Apple</SelectItem>
                                <SelectItem value="banana">Banana</SelectItem>
                                <SelectItem value="blueberry">Blueberry</SelectItem>
                                <SelectItem value="grapes">Grapes</SelectItem>
                                <SelectItem value="pineapple">Pineapple</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <div className="w-[180px] relative">
                    <Select>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="操作行为" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="apple">Apple</SelectItem>
                                <SelectItem value="banana">Banana</SelectItem>
                                <SelectItem value="blueberry">Blueberry</SelectItem>
                                <SelectItem value="grapes">Grapes</SelectItem>
                                <SelectItem value="pineapple">Pineapple</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <Button>重置</Button>
            </div>
            <Table className="mb-[50px]">
                {/* <TableCaption>用户列表.</TableCaption> */}
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">审计ID</TableHead>
                        <TableHead className="w-[200px]">用户名</TableHead>
                        <TableHead className="w-[200px]">用户组</TableHead>
                        <TableHead className="w-[200px]">角色</TableHead>
                        <TableHead className="w-[200px]">操作时间</TableHead>
                        <TableHead className="w-[200px]">系统模块</TableHead>
                        <TableHead className="w-[200px]">操作行为</TableHead>
                        <TableHead className="w-[200px]">操作对象类型</TableHead>
                        <TableHead className="w-[200px]">操作对象</TableHead>
                        <TableHead className="w-[200px]">IP地址</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className="font-medium max-w-md truncate">34</TableCell>
                        <TableCell>小明</TableCell>
                        <TableCell>安全部门</TableCell>
                        <TableCell>普通用户</TableCell>
                        <TableCell>2024-02-02 12:12:12</TableCell>
                        <TableCell>位置模块</TableCell>
                        <TableCell>摸鱼</TableCell>
                        <TableCell>生物</TableCell>
                        <TableCell>鱼</TableCell>
                        <TableCell>192.0.0.2</TableCell>
                    </TableRow>
                    {/* {users.map((el) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium max-w-md truncate">{el.user_name}</TableCell>
                            <TableCell>用户组A</TableCell>
                            <TableCell>角色B</TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                        </TableRow>
                    ))} */}
                </TableBody>
            </Table>
        </div>
        {/* 分页 */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="bisheng-table-footer">
            <p className="desc pl-4">审计管理</p>
            <AutoPagination
                className="float-right justify-end w-full mr-6"
                page={1}
                pageSize={50}
                total={200}
                onChange={(newPage) => console.log(1)}
            />
        </div>
    </div>
};


const useUsers = () => {
    const pageRef = useRef(1)
    const [users, setUsers] = useState<any[]>([]);

    const reload = (page, name) => {
        getUsersApi({ name, page, pageSize: 60 }).then(res => {
            pageRef.current = page
            const opts = res.data.map(el => ({ label: el.user_name, value: el.user_id }))
            setUsers(_ops => page > 1 ? [..._ops, ...opts] : opts)
        })
    }

    // 加载更多
    const loadMore = (name) => {
        reload(pageRef.current + 1, name)
    }

    return {
        users,
        loadMore,
        reload() {
            reload(1, '')
        },
        search(name) {
            reload(1, name)
        }
    }
}