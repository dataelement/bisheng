
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
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { exportCsvDataApi, getAuditAppListApi } from "@/controllers/API/log";
import { useTable } from "@/util/hook";
import { exportCsv, formatDate } from "@/util/utils";
import { useContext, useEffect, useMemo, useReducer, useState } from "react";
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
    sensitive_status: string;
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
                sensitive_status: ''
            };
        default:
            return state;
    }
};

export default function AppUseLog() {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    const { message } = useToast()
    // 20 items per page
    const { page, pageSize, data: datalist, total, loading, setPage, filterData } = useTable({}, (param) => {
        const [start_date, end_date] = getStrTime(param.dateRange || [])
        return getAuditAppListApi({
            page: page,
            page_size: param.pageSize,
            flow_ids: param.appName?.length ? param.appName : undefined,
            user_ids: param.userName?.[0]?.value || undefined,
            group_ids: param.userGroup || undefined,
            start_date,
            end_date,
            feedback: param.feedback || undefined,
            sensitive_status: param.sensitive_status || undefined,
        })
    });
    const processedData = useMemo(() =>
        datalist.map(el => ({
            ...el,
            userGroupsString: el.user_groups.map(item => item.name).join(','),
        })),
        [datalist] // Dependency: datalist
    );

    const [filters, dispatch] = useReducer(filterReducer, {
        appName: [],
        userName: [],
        userGroup: '',
        dateRange: [],
        feedback: '',
        sensitive_status: ''
    });

    const resetClick = () => {
        dispatch({ type: 'RESET' });
        filterData({
            appName: [],
            userName: [],
            userGroup: '',
            dateRange: [],
            feedback: '',
            sensitive_status: ''
        })
    }
    // Cache page before entering detail page, temporary solution
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

    const { user } = useContext(userContext)
    const [auditing, setAuditing] = useState(false);
    const handleExport = async () => {
        const generateFileName = (start_date, end_date, userName) => {
            let str = '';
            if (start_date && end_date) {
                const startDatePart = start_date.split(' ')[0];
                const endDatePart = end_date.split(' ')[0];
                str = `${startDatePart}_${endDatePart}_`;
            }
            return `Export_${str}${userName}_${formatDate(new Date(), 'yyyy-MM-dd_HH-mm-ss')}.csv`;
        };

        setAuditing(true);

        // Handle time range logic
        const dateRange = filters.dateRange || [];
        let originalStart = dateRange[0];
        let originalEnd = dateRange[1];

        let adjustedStart = originalStart;
        let adjustedEnd = originalEnd;
        let showToast = false;
        let toastMessage = '';

        // No time range selected
        if (!originalStart && !originalEnd) {
            adjustedEnd = new Date();
            adjustedStart = new Date(adjustedEnd.getTime() - 59 * 24 * 60 * 60 * 1000); // Last 60 days
            showToast = true;
            toastMessage = t('log.exportNoDateRange');
        }
        // Partial time selection (only start or end selected)
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
            toastMessage = t('log.exportCustomDateRange', { start: formattedStart, end: formattedEnd });
        }
        // Time range selected, check span
        else {
            const diffTime = adjustedEnd.getTime() - adjustedStart.getTime();
            const diffDays = Math.floor(diffTime / (24 * 60 * 60 * 1000)) + 1; // Total days including start and end dates
            if (diffDays > 60) {
                message({
                    variant: 'error',
                    description: t('log.exportDateRangeExceed'),
                })
                setAuditing(false);
                return;
            }
        }

        // Display toast message
        if (showToast) {
            message({
                variant: 'warning',
                description: toastMessage,
            })
        }

        // Generate request parameters
        const [start_date, end_date] = getStrTime([adjustedStart, adjustedEnd])

        exportCsvDataApi({
            flow_ids: filters.appName?.length ? filters.appName : undefined,
            user_ids: filters.userName?.[0]?.value || undefined,
            group_ids: filters.userGroup || undefined,
            start_date,
            end_date,
            feedback: filters.feedback || undefined,
            sensitive_status: filters.sensitive_status || undefined,
        }).then(async res => {
            const data = [
                [
                    t('log.csvHeaders.sessionId'),
                    t('log.csvHeaders.appName'),
                    t('log.csvHeaders.sessionCreationTime'),
                    t('log.csvHeaders.userName'),
                    t('log.csvHeaders.messageRole'),
                    t('log.csvHeaders.messageSendTime'),
                    t('log.csvHeaders.messageContent'),
                    t('log.csvHeaders.like'),
                    t('log.csvHeaders.dislike'),
                    t('log.csvHeaders.copy'),
                    t('log.csvHeaders.sensitiveStatus')
                ]
            ];

            const handleMessage = (msg, category, id) => {
                try {
                    msg = msg && msg[0] === '{' ? JSON.parse(msg) : msg || ''
                } catch (error) {
                    console.error('error :>> ', `${id} ${t('log.messageConversionFailed')}`);
                }
                // output
                if ('output_with_input_msg' === category) return `${msg.msg} :${msg.hisValue}`
                if ('output_with_choose_msg' === category) return `${msg.msg} :${msg.options.find(el => el.id === msg.hisValue)?.label}`
                const newMsg = typeof msg === 'string' ? msg : (msg.input || msg.msg)
                return /^[=+\-@]/.test(newMsg) ? "'" + newMsg : newMsg
            }

            // Data transformation
            res.data.forEach(item => {
                item.messages.forEach(msg => {
                    const { message, category } = msg
                    const usefulMsg = !['flow', 'tool_call', 'tool_result'].includes(category) && message
                    usefulMsg && data.push([
                        item.chat_id,
                        item.flow_name,
                        item.create_time.replace('T', ' '),
                        item.user_name,
                        msg.category === 'question' ? t('log.userRole') : t('log.aiRole'),
                        msg.create_time.replace('T', ' '),
                        handleMessage(message, msg.category, item.flow_id + '_' + item.chat_id),
                        msg.liked === 1 ? t('log.yes') : t('log.no'),
                        msg.liked === 2 ? t('log.yes') : t('log.no'),
                        msg.copied ? t('log.yes') : t('log.no'),
                        msg.sensitive_status === 1 ? t('log.no') : t('log.yes')
                    ])
                })
            })
            // Export to Excel
            const fileName = generateFileName(start_date, end_date, user.user_name);
            exportCsv(data, fileName, true)

            // await downloadFile(__APP_ENV__.BASE_URL + res.url, fileName);
            setAuditing(false);
        }).catch((error) => {
            setAuditing(false);
            // Optional: handle error cases
        });
    };


    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="h-[calc(100vh-128px)] overflow-y-auto px-2 py-4 pb-20">
            <div className="flex flex-wrap gap-4">
                <FilterByApp value={filters.appName} placeholder={t('log.appName')} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['appName']: value } })} />
                <FilterByUser value={filters.userName} placeholder={t('log.userName')} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['userName']: value } })} />
                <FilterByUsergroup value={filters.userGroup} placeholder={t('log.userGroup')} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['userGroup']: value } })} />
                <FilterByDate value={filters.dateRange} placeholders={[`${t('log.startDate')}`, `${t('log.endDate')}`]} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['dateRange']: value } })} />
                <div className="w-[200px] relative">
                    <Select value={filters.feedback} onValueChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['feedback']: value } })}>
                        <SelectTrigger className="w-[200px]">
                            <SelectValue placeholder={t('log.userFeedbackPlaceholder')} />
                        </SelectTrigger>
                        <SelectContent className="max-w-[200px] break-all">
                            <SelectGroup>
                                <SelectItem value={'like'}>{t('log.likeFeedback')}</SelectItem>
                                <SelectItem value={'dislike'}>{t('log.dislikeFeedback')}</SelectItem>
                                <SelectItem value={'copied'}>{t('log.copyFeedback')}</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                {appConfig.isPro && <div className="w-[200px] relative">
                    <Select value={filters.sensitive_status} onValueChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['sensitive_status']: value } })} >
                        <SelectTrigger className="w-[200px]">
                            <SelectValue placeholder={t('log.sensitiveReviewResult')} />
                        </SelectTrigger>
                        <SelectContent className="max-w-[200px] break-all">
                            <SelectGroup>
                                <SelectItem value={'2'}>{t('log.sensitiveViolation')}</SelectItem>
                                <SelectItem value={'1'}>{t('log.sensitivePass')}</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>}
                <Button onClick={() => {
                    const dateRange = filters.dateRange || [];
                    let originalStart = dateRange[0];
                    let originalEnd = dateRange[1];
                    let adjustedStart = originalStart;
                    let adjustedEnd = originalEnd;
                    if (originalStart && !originalEnd) {
                        adjustedEnd = undefined;
                    } else if (!originalStart && originalEnd) {
                        adjustedStart = undefined;
                    }

                    filterData({ ...filters, dateRange: [adjustedStart, adjustedEnd] })
                }} >{t('log.searchButton')}</Button>
                <Button onClick={resetClick} variant="outline">{t('log.resetButton')}</Button>
                <Button onClick={handleExport} disabled={auditing}>
                    {auditing && <LoadIcon className="mr-1" />}{t('log.exportButton')}</Button>
            </div>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('log.appName')}</TableHead>
                        <TableHead>{t('log.userName')}</TableHead>
                        <TableHead>{t('log.userGroup')}</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead>{t('log.userFeedback')}</TableHead>
                        {appConfig.isPro && <TableHead>{t('log.sensitiveReviewResult')}</TableHead>}
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>

                <TableBody>
                    {processedData.map((el: any) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium max-w-[200px]">
                                {/* <div className=" truncate-multiline"></div> */}
                                <div className="truncate-multiline">
                                    {el.flow_type === 15 ? t('log.workbench_daily') : el.flow_name}
                                </div>
                            </TableCell>
                            <TableCell>{el.user_name}</TableCell>
                            <TableCell>{el.userGroupsString}</TableCell>
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
                                {el.sensitive_status === 1 ? <Badge variant="outline" className="text-green-500">{t('log.sensitivePass')}</Badge>
                                    : <Badge variant="outline" className="text-red-500">{t('log.sensitiveViolation')}</Badge>
                                }
                            </TableCell>}
                            <TableCell className="text-right" onClick={() => {
                                // @ts-ignore
                                // window.libname = el.name;
                            }}>
                                {/* <Button variant="link" className="" onClick={() => setOpenData(true)}>Add to dataset</Button> */}
                                {
                                    el.chat_id && <Link
                                        to={el.flow_type === 15 ? `/log/chatlog/${el.chat_id}` : `/log/chatlog/${el.flow_id}/${el.chat_id}/${el.flow_type}`}
                                        className="no-underline hover:underline text-primary"
                                        onClick={handleCachePage}
                                    >{t('lib.details')}</Link>
                                }
                            </TableCell>
                        </TableRow>
                    )
                    )}
                </TableBody>
            </Table>
        </div>
        <div className="bisheng-table-footer px-6 bg-background-login">
            <p className="desc"></p>
            <div>
                <AutoPagination
                    page={page}
                    showJumpInput
                    jumpToText={t('log.pagination.jumpTo')}
                    pageText={t('log.pagination.page')}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
    </div>
};
