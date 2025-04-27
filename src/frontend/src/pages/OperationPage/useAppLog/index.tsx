import FilterByApp from "@/components/bs-comp/filterTableDataComponent/FilterByApp";
import FilterByDate from "@/components/bs-comp/filterTableDataComponent/FilterByDate";
import FilterByUser from "@/components/bs-comp/filterTableDataComponent/FilterByUser";
import FilterByUsergroup from "@/components/bs-comp/filterTableDataComponent/FilterByUsergroup";
import { ThunmbIcon } from "@/components/bs-icons";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { exportOperationDataApi, getChatAnalysisConfigApi, getOperationAppListApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { useEffect, useState } from "react";
import { SearchInput } from "@/components/bs-ui/input";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { getStrTime } from "../StatisticsReport";
import { checkSassUrl } from "@/components/bs-comp/FileView";
import { downloadFile, formatDate } from "@/util/utils";
import { message } from "@/components/bs-ui/toast/use-toast";

export default function AppUseLog({ initFilter, clearFilter }) {
    const { t } = useTranslation();
    const { page, pageSize, data: datalist, total, loading, setPage, filterData, reload } = useTable({}, (param) => {
        const [start_date, end_date] = getStrTime(param.dateRange || [])
        return getOperationAppListApi({
            page: page,
            page_size: param.pageSize,
            flow_ids: param.appName?.length ? param.appName.map(el => el.value) : undefined,
            user_ids: param.userName?.[0]?.value || undefined,
            group_ids: param.userGroup?.[0]?.value || undefined,
            start_date,
            end_date,
            feedback: param.feedback || undefined,
            keyword: param.keyword || undefined,
        })
    });

    const [filters, setFilters] = useState({
        appName: [],
        userName: [],
        userGroup: [],
        dateRange: [],
        feedback: '',
        keyword: '',
    });
    useEffect(() => {
        const _filter = window.OperationFilters;
        if (initFilter) {
            const param = {
                ...filters,
                appName: [{ label: initFilter.name, value: initFilter.flow_id }],
                userGroup: [{ label: initFilter.group_info[0].group_name, value: initFilter.group_info[0].id}],
            }
            setFilters(param)
            filterData(param)
            return;
        }
        if (_filter) {
            setFilters(_filter)
            filterData(_filter)
            delete window.OperationFilters;
        }
    }, [initFilter])

    const searchClick = () => {
        filterData(filters);
    }

    const resetClick = () => {
        const param = {
            appName: [],
            userName: [],
            userGroup: [],
            dateRange: [],
            feedback: '',
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
        window.OperationFilters = filters;
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

    const [auditing, setAuditing] = useState(false);
    
    const handleExport = async () => {
        const generateFileName = (start_date, end_date) => {
            let str = '运营';
            if (start_date && end_date) {
                const startDatePart = start_date.split(' ')[0];
                const endDatePart = end_date.split(' ')[0];
                str = `${startDatePart}_${endDatePart}_`;
            }
            return `Export_${str}_${formatDate(new Date(), 'yyyy-MM-dd_HH-mm-ss')}.xlsx`;
        };
        setAuditing(true);
         // 处理时间范围逻辑
         const dateRange = filters.dateRange || [];
         let originalStart = dateRange[0];
         let originalEnd = dateRange[1];
 
         let adjustedStart = originalStart;
         let adjustedEnd = originalEnd;
         let showToast = false;
         let toastMessage = '';
 
         // 未选择时间范围
         if (!originalStart && !originalEnd) {
             adjustedEnd = new Date();
             adjustedStart = new Date(adjustedEnd.getTime() - 59 * 24 * 60 * 60 * 1000); // 最近60天
             showToast = true;
             toastMessage = '未选择时间范围，已自动为你导出最近 60 天数据';
         }
         // 部分选择时间（只选开始或结束）
         else if (!originalStart || !originalEnd) {
             if (originalStart) {
                 adjustedEnd = new Date(originalStart);
                 adjustedEnd.setDate(adjustedEnd.getDate() + 59);
             } else {
                 adjustedStart = new Date(originalEnd);
                 adjustedStart.setDate(adjustedStart.getDate() - 59);
             }
             showToast = true;
             const formattedStart = formatDate(adjustedStart, 'yyyy-MM-dd');
             const formattedEnd = formatDate(adjustedEnd, 'yyyy-MM-dd');
             toastMessage = `未选择时间范围，已自动为你导出 ${formattedStart} - ${formattedEnd} 数据`;
         }
         // 已选择时间范围，检查跨度
         else {
             const diffTime = adjustedEnd.getTime() - adjustedStart.getTime();
             const diffDays = Math.floor(diffTime / (24 * 60 * 60 * 1000)) + 1; // 包含起止日期的总天数
             if (diffDays > 60) {
                 message({
                     variant: 'error',
                     description: '导出时间范围不能超过 60 天，请缩小范围后重试',
                 })
                 setAuditing(false);
                 return;
             }
         }
 
         // 显示提示信息
         if (showToast) {
             message({
                 variant: 'warning',
                 description: toastMessage,
             })
         }
 
         // 生成请求参数
         const [start_date, end_date] = getStrTime([adjustedStart, adjustedEnd]);
         // TODO：优化点 也许需要把后端的报错暴露出来 
         exportOperationDataApi({
            flow_ids: filters.appName?.map(el => el.value) || undefined,
            user_ids: filters.userName?.[0]?.value || undefined,
            group_ids: filters.userGroup?.[0]?.value || undefined,
            start_date,
            end_date, 
            feedback: filters.feedback || undefined,
            keyword: filters.keyword || undefined,
        }).then((res) => {
            if (res) {
                const fileUrl = res.file_list[0];
                downloadFile(checkSassUrl(fileUrl), generateFileName(start_date, end_date));
            } else {
                console.error('导出失败');
            }
            setAuditing(false);
        })
    }

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
                                    <SelectItem value={'copied'}>复制</SelectItem>
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <SearchInput className="w-64" value={filters.keyword} placeholder={'历史聊天记录查询'} onChange={(e) => handleFilterChange('keyword', e.target.value)}></SearchInput>
                    <Button onClick={searchClick} >查询</Button>
                    <Button onClick={resetClick} variant="outline">重置</Button>
                    <Button onClick={handleExport} disabled={auditing}>
                        {auditing && <LoadIcon className="mr-1" />}导出 
                    </Button>
                </div>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[300px]">{t('log.appName')}</TableHead>
                            <TableHead>{t('log.userName')}</TableHead>
                            <TableHead>{t('system.userGroup')}</TableHead>
                            <TableHead>{t('updateTime')}</TableHead>
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
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
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
