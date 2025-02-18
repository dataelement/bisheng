import FilterByApp from "@/components/bs-comp/filterTableDataComponent/FilterByApp";
import FilterByDate from "@/components/bs-comp/filterTableDataComponent/FilterByDate";
import FilterByUsergroup from "@/components/bs-comp/filterTableDataComponent/FilterByUsergroup";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";

export default function StatisticsReport({ onBack }) {
    const [filters, setFilters] = useState({
        userGroup: '',
        appName: '',
        dateRange: [],  // TODO 默认值  -7  -1
    });
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize] = useState(20);
    const [sortConfig, setSortConfig] = useState({ key: '', direction: 'asc' });

    useEffect(() => {
        fetchReportData();
    }, [filters, page, sortConfig]);

    const fetchReportData = async () => {
        setLoading(true);
        const params = {
            ...filters,
            page,
            pageSize,
            sortKey: sortConfig.key,
            sortDirection: sortConfig.direction
        };
        const res = await getStatisticsReportData(params);
        setData(res.data);
        setTotal(res.total);
        setLoading(false);
    };

    const handleSearch = () => {
        setPage(1);
        fetchReportData();
    };

    const handleReset = () => {
        setFilters({
            userGroup: '',
            appName: '',
            startDate: '',
            endDate: ''
        });
        setPage(1);
        fetchReportData();
    };

    const handleExport = () => {
        // TODO 导出excle
        exportStatisticsReport(filters).then(() => {
            // handle success or show toast
        });
    };

    const handleSort = (column) => {
        let direction = 'asc';
        if (sortConfig.key === column && sortConfig.direction === 'asc') {
            direction = 'desc';
        }
        setSortConfig({ key: column, direction });
    };

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
                <span>统计报表</span>
            </div>
            <div className="h-[calc(100vh-132px)] overflow-y-auto px-2 py-4 pb-10">
                {/* 筛选区 */}
                <div className="flex flex-wrap gap-4 mb-6">
                    <FilterByApp value={filters.appName} onChange={(value) => setFilters({ ...filters, appName: value })} />
                    <FilterByUsergroup value={filters.userGroup} onChange={(value) => setFilters({ ...filters, userGroup: value })} />
                    <FilterByDate value={filters.dateRange} onChange={(value) => setFilters({ ...filters, dateRange: [] })} />

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
                            <TableHead onClick={() => handleSort('sessionCount')}>会话数</TableHead>
                            <TableHead onClick={() => handleSort('userInputCount')}>用户输入消息数</TableHead>
                            <TableHead>应用输出消息数</TableHead>
                            <TableHead onClick={() => handleSort('violationCount')}>违规消息数</TableHead>
                        </TableRow>
                    </TableHeader>

                    <TableBody>
                        {data.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={6} className="text-center">暂无数据</TableCell>
                            </TableRow>
                        ) : (
                            data.map((row, idx) => (
                                <TableRow key={idx}>
                                    <TableCell>{row.userGroup}</TableCell>
                                    <TableCell>{row.appName}</TableCell>
                                    <TableCell>{row.sessionCount}</TableCell>
                                    <TableCell>{row.userInputCount}</TableCell>
                                    <TableCell>{row.appOutputCount}</TableCell>
                                    <TableCell>
                                        {/* TODO 跳转到上一页,填充应用 用户名 违规,然后查询 */}
                                        <a href="#">{row.violationCount}</a>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>

                {/* 分页 */}
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
        </div>
    );
}



const mockData = [
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 1', appName: '应用 A', sessionCount: 150, userInputCount: 2000, appOutputCount: 1800, violationCount: 20 },
    { userGroup: '用户组 2', appName: '应用 B', sessionCount: 100, userInputCount: 1200, appOutputCount: 1100, violationCount: 5 }
];

export const getStatisticsReportData = async (params) => {
    // Simulate an API call
    return {
        data: mockData,
        total: mockData.length
    };
};

export const exportStatisticsReport = async (filters) => {
    console.log('Exporting data with filters:', filters);
    return true;
};