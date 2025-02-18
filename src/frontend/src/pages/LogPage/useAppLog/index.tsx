import { useState, useEffect } from "react";
import FilterByApp from "@/components/bs-comp/filterTableDataComponent/FilterByApp";
import FilterByDate from "@/components/bs-comp/filterTableDataComponent/FilterByDate";
import FilterByUser from "@/components/bs-comp/filterTableDataComponent/FilterByUser";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import FilterByUsergroup from "@/components/bs-comp/filterTableDataComponent/FilterByUsergroup";
import { ThunmbIcon } from "@/components/bs-icons";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { getChatLabelsApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Button } from "@/components/bs-ui/button";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

export default function AppUseLog() {
    const { t } = useTranslation();
    const { page, pageSize, data: datalist, total, loading, setPage, filterData } = useTable({}, (param) =>
        getChatLabelsApi(param).then(res => ({ ...res, data: res.list }))
    );

    const [filters, setFilters] = useState({
        appName: [],
        userName: [],
        userGroup: '',
        dateRange: [],
        feedback: '',
        result: ''
    });

    const [showReviewResult, setShowReviewResult] = useState(true); // State to control the visibility of the review result column

    // 进详情页前缓存 page, 临时方案
    const handleCachePage = () => {
        window.LogPage = page;
    };

    useEffect(() => {
        const _page = window.LogPage;
        if (_page) {
            setPage(_page);
            delete window.LogPage;
        } else {
            setPage(1);
        }
    }, []);

    const handleFilterChange = (filterType, value) => {
        const updatedFilters = { ...filters, [filterType]: value };
        setFilters(updatedFilters);

        // Send the updated filters to the filterData function
        filterData(updatedFilters);
    };

    // Function to determine the class based on review result
    const getResultClass = (result) => {
        switch (result) {
            case 'a': return 'text-green-500'; // 通过
            case 'b': return 'text-red-500';   // 违规
            case 'c': return 'text-gray-500';  // 未审查
            case 'd': return 'text-orange-500';// 审查失败
            default: return '';
        }
    };

    const handleRunClick = () => {
        bsConfirm({
            title: t('prompt'),
            desc: '会话批量审查可能需要较长耗时，确认进行审查？',
            okTxt: t('confirm'),
            onOk(next) {
                // filters
                next()
            }
        })
    }

    return (
        <div className="relative">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}
            <div className="h-[calc(100vh-128px)] overflow-y-auto px-2 py-4 pb-10">
                <div className="flex flex-wrap gap-4">
                    <FilterByApp value={filters.appName} onChange={(value) => handleFilterChange('appName', value)} />
                    <FilterByUser value={filters.userName} onChange={(value) => handleFilterChange('userName', value)} />
                    <FilterByUsergroup value={filters.userGroup} onChange={(value) => handleFilterChange('userGroup', value)} />
                    <FilterByDate value={filters.dateRange} onChange={(value) => handleFilterChange('dateRange', value)} />
                    <div className="w-[200px] relative">
                        <Select onValueChange={(value) => handleFilterChange('feedback', value)}>
                            <SelectTrigger className="w-[200px]">
                                <SelectValue placeholder="用户反馈" />
                            </SelectTrigger>
                            <SelectContent className="max-w-[200px] break-all">
                                <SelectGroup>
                                    <SelectItem value={'a'}>赞</SelectItem>
                                    <SelectItem value={'b'}>踩</SelectItem>
                                    <SelectItem value={'c'}>复制</SelectItem>
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="w-[200px] relative">
                        <Select onValueChange={(value) => handleFilterChange('result', value)}>
                            <SelectTrigger className="w-[200px]">
                                <SelectValue placeholder="审查结果" />
                            </SelectTrigger>
                            <SelectContent className="max-w-[200px] break-all">
                                <SelectGroup>
                                    <SelectItem value={'a'}>通过</SelectItem>
                                    <SelectItem value={'b'}>违规</SelectItem>
                                    <SelectItem value={'c'}>未审查</SelectItem>
                                    <SelectItem value={'d'}>审查失败</SelectItem>
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <Button onClick={handleRunClick}>手动审查</Button>
                </div>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">{t('log.appName')}</TableHead>
                            <TableHead>{t('log.userName')}</TableHead>
                            <TableHead>{t('system.userGroup')}</TableHead>
                            <TableHead>{t('createTime')}</TableHead>
                            {showReviewResult && <TableHead>审查结果</TableHead>} {/* Conditionally render the review result column */}
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
                                <TableCell>{el.user_name}</TableCell>
                                <TableCell>{el.create_time.replace('T', ' ')}</TableCell>

                                {showReviewResult && (
                                    <TableCell className={getResultClass('b')}>
                                        {el.review_result === 'a' && '通过'}
                                        {'b' === 'b' && '违规'}
                                        {el.review_result === 'c' && '未审查'}
                                        {el.review_result === 'd' && '审查失败'}
                                    </TableCell>
                                )}

                                <TableCell className="text-right" onClick={() => {
                                    // @ts-ignore
                                    // window.libname = el.name;
                                }}>
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
    );
}
