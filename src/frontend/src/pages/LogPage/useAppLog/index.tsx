
import FilterByApp from "@/components/bs-comp/filterTableDataComponent/FilterByApp";
import FilterByDate from "@/components/bs-comp/filterTableDataComponent/FilterByDate";
import FilterByUser from "@/components/bs-comp/filterTableDataComponent/FilterByUser";
import FilterByUsergroup from "@/components/bs-comp/filterTableDataComponent/FilterByUsergroup";
import { ThunmbIcon } from "@/components/bs-icons";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { locationContext } from "@/contexts/locationContext";
import { getAuditAppListApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { downloadFile, formatDate } from "@/util/utils";
import { useContext, useEffect, useReducer, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
const getStrTime = (date) => {
    const start_date = date[0] && (formatDate(date[0], 'yyyy-MM-dd') + ' 00:00:00')
    const end_date = date[1] && (formatDate(date[1], 'yyyy-MM-dd') + ' 23:59:59')
    return [start_date, end_date]
}

type FilterState = {
    appName: any[];
    userName: any[];
    userGroup: string;
    dateRange: any[];
    feedback: string;
    result: string;
};

type Action =
    | { type: 'SET_FILTER'; payload: Partial<FilterState> }
    | { type: 'RESET' };

const filterReducer = (state: FilterState, action: Action): FilterState => {
    switch (action.type) {
        case 'SET_FILTER':
            return { ...state, ...action.payload };
        case 'RESET':
            return {
                appName: [],
                userName: [],
                userGroup: '',
                dateRange: [],
                feedback: '',
                result: ''
            };
        default:
            return state;
    }
};

export default function AppUseLog() {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    // 20条每页
    const { page, pageSize, data: datalist, total, loading, setPage, filterData } = useTable({}, (param) => {
        const [start_date, end_date] = getStrTime(param.dateRange || [])
        return getAuditAppListApi({
            page: page,
            page_size: param.pageSize,
            flow_ids: param.appName?.length ? param.appName.map(el => el.value) : undefined,
            user_ids: param.userName?.[0]?.value || undefined,
            group_ids: param.userGroup || undefined,
            start_date,
            end_date,
            feedback: param.feedback || undefined,
            // review_status: param.result || undefined,
        })
    });

    const [filters, dispatch] = useReducer(filterReducer, {
        appName: [],
        userName: [],
        userGroup: '',
        dateRange: [],
        feedback: '',
        result: ''
    });

    const resetClick = () => {
        dispatch({ type: 'RESET' });
        filterData({
            appName: [],
            userName: [],
            userGroup: '',
            dateRange: [],
            feedback: '',
            result: ''
        })
    }
    // 进详情页前缓存 page, 临时方案
    const handleCachePage = () => {
        window.LogPage = page
    }
    useEffect(() => {
        const _page = window.LogPage
        if (_page) {
            setPage(_page);
            delete window.LogPage
        } else {
            setPage(1);
        }
    }, [])

    const [auditing, setAuditing] = useState(false);
    const handleExport = async () => {
        setAuditing(true)
        await downloadFile('url', 'text.csv') // csv zip
        setAuditing(false)
    }


    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="h-[calc(100vh-128px)] overflow-y-auto px-2 py-4 pb-20">
            <div className="flex flex-wrap gap-4">
                <FilterByApp value={filters.appName} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['appName']: value } })} />
                <FilterByUser value={filters.userName} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['userName']: value } })} />
                <FilterByUsergroup value={filters.userGroup} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['userGroup']: value } })} />
                <FilterByDate value={filters.dateRange} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['dateRange']: value } })} />
                <div className="w-[200px] relative">
                    <Select value={filters.feedback} onValueChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['feedback']: value } })}>
                        <SelectTrigger className="w-[200px]">
                            <SelectValue placeholder="用户反馈" />
                        </SelectTrigger>
                        <SelectContent className="max-w-[200px] break-all">
                            <SelectGroup>
                                <SelectItem value={'like'}>赞</SelectItem>
                                <SelectItem value={'dislike'}>踩</SelectItem>
                                <SelectItem value={'copied'}>复制</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                {appConfig.isPro && <div className="w-[200px] relative">
                    <Select value={filters.result} onValueChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['result']: value } })} >
                        <SelectTrigger className="w-[200px]">
                            <SelectValue placeholder="实时内容安全审查结果" />
                        </SelectTrigger>
                        <SelectContent className="max-w-[200px] break-all">
                            <SelectGroup>
                                <SelectItem value={'violate'}>违规</SelectItem>
                                <SelectItem value={'pass'}>通过</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>}
                <Button onClick={() => filterData(filters)} >查询</Button>
                <Button onClick={resetClick} variant="outline">重置</Button>
                <Button onClick={handleExport} disabled={auditing}>
                    {auditing && <LoadIcon className="mr-1" />}导出</Button>
            </div>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('log.appName')}</TableHead>
                        <TableHead>{t('log.userName')}</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead>{t('log.userFeedback')}</TableHead>
                        {appConfig.isPro && <TableHead>实时内容安全审查结果</TableHead>}
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
                            {appConfig.isPro && <TableCell>
                                <Badge variant="outline" className="text-green-500">通过</Badge>
                                <Badge variant="outline" className="text-red-500">违规</Badge>
                            </TableCell>}
                            <TableCell className="text-right" onClick={() => {
                                // @ts-ignore
                                // window.libname = el.name;
                            }}>
                                {/* <Button variant="link" className="" onClick={() => setOpenData(true)}>添加到数据集</Button> */}
                                {
                                    el.chat_id && <Link
                                        to={`/log/chatlog/${el.flow_id}/${el.chat_id}/${el.flow_type}`}
                                        className="no-underline hover:underline text-primary"
                                        onClick={handleCachePage}
                                    >{t('lib.details')}</Link>
                                }
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
                    showJumpInput
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
    </div>
};
