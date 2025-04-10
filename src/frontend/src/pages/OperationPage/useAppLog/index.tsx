import FilterByApp from "@/components/bs-comp/filterTableDataComponent/FilterByApp";
import FilterByDate from "@/components/bs-comp/filterTableDataComponent/FilterByDate";
import FilterByUser from "@/components/bs-comp/filterTableDataComponent/FilterByUser";
import FilterByUsergroup from "@/components/bs-comp/filterTableDataComponent/FilterByUsergroup";
import { ThunmbIcon } from "@/components/bs-icons";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { getOperationAppListApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { useEffect, useState } from "react";
import { SearchInput } from "@/components/bs-ui/input";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { getStrTime } from "../StatisticsReport";

export default function AppUseLog({ initFilter, clearFilter }) {
    const { t } = useTranslation();
    const { page, pageSize, data: datalist, total, loading, setPage, filterData, reload } = useTable({}, (param) => {
        const [start_date, end_date] = getStrTime(param.dateRange || [])
        return getOperationAppListApi({
            page: page,
            page_size: param.pageSize,
            flow_ids: param.appName?.length ? param.appName.map(el => el.value) : undefined,
            user_ids: param.userName?.[0]?.value || undefined,
            group_ids: param.userGroup || undefined,
            start_date,
            end_date,
            feedback: param.feedback || undefined,
            review_status: param.result || undefined,
            keyword: param.keyword || undefined,
        })
    });

    const [filters, setFilters] = useState({
        appName: [],
        userName: [],
        userGroup: '',
        dateRange: [],
        feedback: '',
        result: '',
        keyword: '',
    });
    useEffect(() => {
        if (initFilter) {
            const param = {
                ...filters,
                appName: [{ label: initFilter.name, value: initFilter.flow_id }],
                userGroup: initFilter.group_info[0].id,
                result: '3'
            }
            setFilters(param)
            filterData(param)
        }
    }, [initFilter])

    const searchClick = () => {
        filterData(filters);
    }

    const resetClick = () => {
        const param = {
            appName: [],
            userName: [],
            userGroup: '',
            dateRange: [],
            feedback: '',
            result: '',
            keyword: '',
        }
        setFilters(param)
        filterData(param)
    }
    const handleFilterChange = (filterType, value) => {
        const updatedFilters = { ...filters, [filterType]: value };
        setFilters(updatedFilters);
    };


    // 进详情页前缓存 page, 临时方案
    const handleCachePage = (el) => {
        // 是否违规
        localStorage.setItem('reviewStatus', el.review_status.toString());
        // 搜索的历史记录
        localStorage.setItem('operationKeyword', filters.keyword);
        window.OperationPage = page;
    };

    useEffect(() => {
        const _page = window.OperationPage;
        if (_page) {
            setPage(_page);
            delete window.OperationPage;
        } else {
            setPage(1);
        }
    }, []);

    return (
        <div className="relative">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}
            <div className="h-[calc(100vh-128px)] overflow-y-auto px-2 py-4 pb-20">
                <div className="flex flex-wrap gap-4">
                    <FilterByApp isAudit={false} value={filters.appName} onChange={(value) => handleFilterChange('appName', value)} />
                    <FilterByUser isAudit={false} value={filters.userName} onChange={(value) => handleFilterChange('userName', value)} />
                    <FilterByUsergroup isAudit={false} value={filters.userGroup} onChange={(value) => handleFilterChange('userGroup', value)} />
                    <FilterByDate value={filters.dateRange} onChange={(value) => handleFilterChange('dateRange', value)} />
                    <div className="w-[200px] relative">
                        <Select value={filters.feedback} onValueChange={(value) => handleFilterChange('feedback', value)}>
                            <SelectTrigger className="w-[200px]">
                                <SelectValue placeholder="用户反馈" />
                            </SelectTrigger>
                            <SelectContent className="max-w-[200px] break-all">
                                <SelectGroup>
                                    <SelectItem value={'like'}>赞</SelectItem>
                                    <SelectItem value={'dislike'}>踩</SelectItem>
                                    <SelectItem value={'copied'}>反馈</SelectItem>
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <SearchInput className="w-64" placeholder={'历史记录'} onChange={(e) => handleFilterChange('keyword', e.target.value)}></SearchInput>
                    <Button onClick={searchClick} >查询</Button>
                    <Button onClick={resetClick} variant="outline">重置</Button>
                </div>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[300px]">{t('log.appName')}</TableHead>
                            <TableHead>{t('log.userName')}</TableHead>
                            <TableHead>{t('system.userGroup')}</TableHead>
                            <TableHead>{t('createTime')}</TableHead>
                            <TableHead>{t('log.userFeedback')}</TableHead>
                            <TableHead className="text-right">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>

                    <TableBody>
                        {datalist.map((el: any, index) => (
                            <TableRow key={`${el.id}${index}`}>
                                <TableCell className="font-medium max-w-[200px]">
                                    <div className=" truncate-multiline">{el.flow_name}</div>
                                </TableCell>
                                <TableCell>{el.user_name}</TableCell>
                                <TableCell>{el.user_groups.map(el => el.name).join(',')}</TableCell>
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

                                <TableCell className="text-right">
                                    {
                                        el.chat_id && <Link
                                            to={`/operation/chatLog/${el.flow_id}/${el.chat_id}/${el.flow_type}`}
                                            className="no-underline hover:underline text-primary"
                                            onClick={() => handleCachePage(el)}
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
    );
}
