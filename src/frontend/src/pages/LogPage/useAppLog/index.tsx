
import { ThunmbIcon } from "@/components/bs-icons";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { getChatLabelsApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { t } from "i18next";
import { useEffect } from "react";
import { Link } from "react-router-dom";

export default function AppUseLog() {

    // 20条每页
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({}, (param) =>
        getChatLabelsApi(param).then(res => ({ ...res, data: res.list }))
    )

    // 进详情页前缓存 page, 临时方案
    const handleCachePage = () => {
        window.LibPage = page
    }
    useEffect(() => {
        const _page = window.LibPage
        if (_page) {
            setPage(_page);
            delete window.LibPage
        } else {
            setPage(1);
        }
    }, [])

    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="h-[calc(100vh-128px)] overflow-y-auto pb-20">
            <div className="flex justify-end gap-4 items-center">
                <SearchInput placeholder="搜索" onChange={(e) => search(e.target.value)} />
            </div>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">应用名称</TableHead>
                        <TableHead>用户名</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead>用户反馈</TableHead>
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>

                <TableBody>
                    {datalist.map((el: any) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium max-w-[200px]">
                                <div className=" truncate-multiline">{el.flow_name}</div>
                            </TableCell>
                            <TableCell>{el.user_name}</TableCell>
                            <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                            <TableCell className="max-w-[300px] break-all flex gap-2">
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
                                        className={`cursor-pointer`}
                                    />
                                    <span className="left-4 top-[-4px] break-keep">--</span>
                                </div>
                            </TableCell>
                            <TableCell className="text-right" onClick={() => {
                                // @ts-ignore
                                // window.libname = el.name;
                            }}>
                                {/* <Button variant="link" className="" onClick={() => setOpenData(true)}>添加到数据集</Button> */}
                                <Link to={`/chatlog/${el.flow_id}/${el.chat_id}`} className="no-underline hover:underline text-primary" onClick={handleCachePage}>{t('lib.details')}</Link>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
        <div className="bisheng-table-footer px-6 bg-background-login">
            <p className="desc"></p>
            <div>
                <AutoPagination
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
    </div>
};
