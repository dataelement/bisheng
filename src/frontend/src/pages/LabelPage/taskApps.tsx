import ColFilterUser from "@/components/bs-comp/tableComponent/ColFilterUser";
import { ThunmbIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { TableHeadEnumFilter } from "@/components/bs-ui/select/filter";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { getChatLabelsApi, getMarkChatsApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

export default function taskApps() {
    const { id } = useParams()
    const navigator = useNavigate()

    const { page, pageSize, total, data: datalist, loading, setPage, filterData } = useTable({}, (param) =>
        getMarkChatsApi({
            ...param,
            task_id: id
        }).then(res => ({ ...res, pageSize: param, data: res.list }))
    )

    return <div className="h-full">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="bg-background-login px-4 overflow-y-auto h-full pb-20">
            <div className="flex justify-between items-center py-4">
                <div className="flex items-center">
                    <ShadTooltip content="back" side="top">
                        <Button
                            className="w-[36px] px-2 rounded-full"
                            variant="outline"
                            onClick={() => navigator('/label')}
                        ><ArrowLeft className="side-bar-button-size" /></Button>
                    </ShadTooltip>
                    <span className=" text-gray-700 text-sm font-black pl-4">{id}</span>
                </div>
            </div>
            <div className="flex-grow-0">
                <Table className="">
                    <TableHeader>
                        <TableRow>
                            <TableHead>应用名称</TableHead>
                            <TableHead>会话创建时间</TableHead>
                            <TableHead>用户反馈</TableHead>
                            <TableHead className="w-[120px]">
                                <div className="flex items-center">
                                    标注状态
                                    <TableHeadEnumFilter options={[
                                        { label: '全部', value: '0' },
                                        { label: '未标注', value: '1' },
                                        { label: '已标注', value: '2' },
                                        { label: '无需标注', value: '3' }
                                    ]}
                                        onChange={(v) => filterData({ mark_status: v })} />
                                </div>
                            </TableHead>
                            <TableHead className="w-[140px]">
                                <div className="flex items-center">
                                    标注人
                                    <ColFilterUser label={id} onFilter={(ids) => filterData({ mark_user: ids })}></ColFilterUser>
                                </div>
                            </TableHead>
                            <TableHead className="w-[80px] text-right">操作</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el, index) => (
                            <TableRow key={index}>
                                <TableCell>{el.flow_name}</TableCell>
                                <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                                <TableCell className="break-all flex gap-2">
                                    <div className="text-center text-xs relative">
                                        <ThunmbIcon
                                            type='like'
                                            className={`cursor-pointer ${el.like_count && 'text-primary hover:text-primary'}`}
                                        />
                                        <span className="left-4 top-[-4px] break-keep">{el.like_count}</span>
                                    </div>
                                    <div className="text-center text-xs relative">
                                        <ThunmbIcon
                                            type='unLike'
                                            className={`cursor-pointer ${el.dislike_count && 'text-primary hover:text-primary'}`}
                                        />
                                        <span className="left-4 top-[-4px] break-keep">{el.dislike_count}</span>
                                    </div>
                                    <div className="text-center text-xs relative">
                                        <ThunmbIcon
                                            type='copy'
                                            className={`cursor-pointer ${el.copied_count && 'text-primary hover:text-primary'}`}
                                        />
                                        <span className="left-4 top-[-4px] break-keep">{el.copied_count}</span>
                                    </div>
                                </TableCell>
                                <TableCell>{['', '未标注', '已标注', '无需标注'][el.mark_status || 1]}</TableCell>
                                <TableCell>{el.mark_user || '-'}</TableCell>
                                <TableCell className="text-right" onClick={() => {
                                    // @ts-ignore
                                    // window.libname = el.name;
                                }}>
                                    {/* <Button variant="link" className="" onClick={() => setOpenData(true)}>添加到数据集</Button> */}
                                    {
                                        el.chat_id && <Link
                                            to={`/label/chat/${id}/${el.flow_id}/${el.chat_id}/${el.flow_type}`}
                                            className="no-underline hover:underline text-primary"
                                        // onClick={handleCachePage}
                                        >查看</Link>
                                    }
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                    <TableFooter>
                        {!datalist.length && (
                            <TableRow>
                                <TableCell colSpan={6} className="text-center text-gray-400">暂无数据</TableCell>
                            </TableRow>
                        )}
                    </TableFooter>
                </Table>
            </div>
            <div className="bisheng-table-footer bg-background-login px-2">
                {/* <p className="desc">xxxx</p> */}
                <AutoPagination
                    className="float-right justify-end w-full mr-6"
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
    </div>;
};
