import FilterByApp from "@/components/bs-comp/filterTableDataComponent/FilterByApp";
import FilterByDate from "@/components/bs-comp/filterTableDataComponent/FilterByDate";
import FilterByUsergroup from "@/components/bs-comp/filterTableDataComponent/FilterByUsergroup";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import GoodEvaluateSelect from './components/GoodEvaluateSelect';
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { getOperationChatStatisticsApi, getOperationReportDownloadLinkApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { downloadFile, formatDate } from "@/util/utils";
import { ArrowLeft, ChevronDown, ChevronsUpDown } from "lucide-react";
import { useState } from "react";

export const getStrTime = (date) => {
    const start_date = date[0] && (formatDate(date[0], 'yyyy-MM-dd') + ' 00:00:00')
    const end_date = date[1] && (formatDate(date[1], 'yyyy-MM-dd') + ' 23:59:59')
    return [start_date, end_date]
}

export default function StatisticsReport({ onBack, onJump }) {
    const [filters, setFilters] = useState(() => {
        const now = new Date();
        const now2 = new Date();
        return {
            userGroup: [],
            appName: [],
            dateRange: [new Date(now.setDate(now.getDate() - 7)), new Date(now2.setDate(now2.getDate() - 1))],
        }
    });


    const [sortConfig, setSortConfig] = useState({ key: '', direction: 'asc' });
    const { page, pageSize, originData, data: datalist, loading, total, setPage, reload, filterData } = useTable({}, (param) => {
        const [start_date, end_date] = getStrTime(filters.dateRange)
        return getOperationChatStatisticsApi({
            flow_ids: filters.appName.map(el => el.value),
            group_ids: filters.userGroup?.[0]?.value || undefined,
            start_date,
            end_date,
            page: param.page,
            page_size: param.pageSize,
            order_field: sortConfig.key,
            order_type: sortConfig.direction
        })
    });

    const handleSearch = (params) => {
        setSortConfig({ key: '', direction: 'asc' });
        setPage(1)
    }
    const handleReset = () => {
        setSortConfig({ key: '', direction: 'asc' });
        const now = new Date();
        const now2 = new Date();
        const param = {
            userGroup: [],
            appName: [],
            dateRange: [new Date(now.setDate(now.getDate() - 7)), new Date(now2.setDate(now2.getDate() - 1))],
        }
        setFilters(param)

        setTimeout(() => setPage(1), 0);
    };

    const handleExport = () => {
        const [start_date, end_date] = getStrTime(filters.dateRange)
        const params = {
            flow_ids: filters.appName.map(el => el.value),
            group_ids: filters.userGroup?.[0]?.value || undefined,
            like_type: goodValue,
            start_date,
            end_date,
        };
        const startDate = start_date.split(' ')?.[0];
        const endDate = end_date.split(' ')?.[0];
        const fileName =  `运营报表_${startDate}_${endDate}.xlsx`

        getOperationReportDownloadLinkApi(params).then(res => {
            downloadFile(__APP_ENV__.BASE_URL + res.url, fileName)
        })
    };

    const handleSort = (column) => {
        let direction = 'asc';
        if (sortConfig.key === column) {
            direction = sortConfig.direction === 'asc' ? 'desc' : 'asc'; // Toggle direction
        } else {
            direction = 'asc'; // Default to ascending for new column
        }
        setSortConfig({ key: column, direction }); // Set the current column and direction
        setTimeout(() => setPage(1), 0);
    };

    const [goodValue, setGoodValue] = useState('2')
    const handleChangeGood = (v) => {
        console.log('---------v', v)
        setGoodValue(v)
    }

    function calculatePercentage(row, goodValue = '1') {
        // 1. 检查 row 是否存在且包含必要的属性
        if (!row || typeof row !== 'object') return '0%';
        
        // 6. 格式化为百分比字符串（保留2位小数）
        return ((goodValue === '1' ? row.satisfaction : row.not_nosatisfaction) * 100).toFixed(2) + '%';
      }

    return (
        <div className="relative py-4">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}
            <div className="flex ml-6 items-center gap-x-3">
                <ShadTooltip content="返回" side="right">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={onBack}>
                        <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                {/* 运营视角 */}
                <span>统计报表</span>
            </div>
            <div className="h-[calc(100vh-132px)] overflow-y-auto px-2 py-4 pb-10">
                {/* 筛选区 */}
                <div className="flex flex-wrap gap-4 mb-6">
                    <FilterByApp isAudit={false} value={filters.appName} onChange={(value) => setFilters({ ...filters, appName: value })} />
                    <FilterByUsergroup isAudit={false} value={filters.userGroup} onChange={(value) => setFilters({ ...filters, userGroup: value })} />
                    <FilterByDate value={filters.dateRange} onChange={(value) => setFilters({ ...filters, dateRange: value })} />

                    <div className="flex gap-4">
                        <Button onClick={handleSearch}>查询</Button>
                        <Button variant="outline" onClick={handleReset}>重置</Button>
                        <Button variant="outline" onClick={handleExport}>导出</Button>
                    </div>
                </div>

                {/* 表格 */}
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>用户组</TableHead>
                            <TableHead>应用名称</TableHead>
                            <TableHead onClick={() => handleSort(goodValue === '1' ? 'likes' : 'not_dislikes')}>
                                <div className="flex items-center gap-x-1">
                                    好评数
                                    {['likes', 'not_dislikes'].includes(sortConfig.key) ? (
                                        <ChevronDown size={18} className={sortConfig.direction === 'asc' && 'rotate-180'} />
                                    ) : (
                                        <ChevronsUpDown size={18} />
                                    )}
                                <GoodEvaluateSelect onChange={handleChangeGood} value={goodValue}/>
                                </div>
                            </TableHead>
                            <TableHead onClick={() => handleSort('input_num')}>
                                <div className="flex items-center gap-x-1">
                                    差评数
                                    {sortConfig.key === 'input_num' ? (
                                        <ChevronDown size={18} className={sortConfig.direction === 'asc' && 'rotate-180'} />
                                    ) : (
                                        <ChevronsUpDown size={18} />
                                    )}
                                </div>
                            </TableHead>
                            <TableHead>应用满意度(%)</TableHead>
                            <TableHead onClick={() => handleSort('violations_num')}>
                                <div className="flex items-center gap-x-1">
                                    会话数
                                    {sortConfig.key === 'session_num' ? (
                                        <ChevronDown size={18} className={sortConfig.direction === 'asc' && 'rotate-180'} />
                                    ) : (
                                        <ChevronsUpDown size={18} />
                                    )}
                                </div>
                            </TableHead>
                        </TableRow>
                    </TableHeader>

                    <TableBody>
                        {datalist.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={6} className="text-center">暂无数据</TableCell>
                            </TableRow>
                        ) : (
                            datalist.map((row, idx) => (
                                <TableRow key={idx}>
                                    <TableCell>{row.group_info.map(el => el.group_name).join(',')}</TableCell>
                                    <TableCell>{row.name}</TableCell>
                                    {/* 好评数（区分分类1 分类2） */}
                                    <TableCell>{goodValue === '1' ? row.likes : row.not_dislikes}</TableCell>
                                    {/* 差评数 */}
                                    <TableCell>{row.dislikes}</TableCell>
                                    {/* 应用满意度 (根据好评数分类来看)*/}
                                    <TableCell>{calculatePercentage(row, goodValue)}</TableCell>
                                    {/* 会话数 */}
                                    <TableCell>
                                        <a className="cursor-pointer text-primary" onClick={() => {
                                            onJump(row)
                                            onBack()
                                        }}>{row.session_num}</a>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>

                {/* 分页 */}
                <div className="bisheng-table-footer px-6 bg-background-login">
                    <p className="desc">{`会话总数：${originData.total_session_num}`}</p>
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
        </div >
    );
}

