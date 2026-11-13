// @ts-strict-ignore
import { Pagination, Button, DatePicker, Select, toast } from '@bisheng/ui';
import type { DatePickerError, DatePickerOpenRange } from '@bisheng/ui';
import { addDays, differenceInCalendarDays, parseISO } from 'date-fns';

import FilterByApp from "@/components/bs-comp/filterTableDataComponent/FilterByApp";
import FilterByUsergroup from "@/components/bs-comp/filterTableDataComponent/FilterByUsergroup";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { useDatePickerLocale } from "@/hooks/useDatePickerLocale";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";

import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { AuditUsageType, EMPTY_ORG_SELECTION, exportCsvDataApi, getAuditAppListApi, getAuditSessionUsersApi } from "@/controllers/API/log";
import type { OrgSelection } from "@/types/api/audit";
import { AuditEmptyState } from "../components/AuditEmptyState";
import { OrgFilter } from "../components/OrgFilter";
import { orgLabel } from "../components/OrgFilter/orgLabel";
import { OrgPathText } from "../components/OrgPathText";
import { useTable } from "@/util/hook";
import { exportCsv, formatDate } from "@/util/utils";
import { useContext, useEffect, useMemo, useReducer, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import styles from "../AuditFilters.module.css";

const getDateBounds = (range?: DatePickerOpenRange | null) => ({
    start_date: range?.[0] ? `${range[0]} 00:00:00` : undefined,
    end_date: range?.[1] ? `${range[1]} 23:59:59` : undefined,
});

type FilterState = {
    appName: any[];
    userId: number | null;
    userGroup: string;
    dateRange: DatePickerOpenRange | null;
    feedback: string;
    sensitive_status: string;
    org: OrgSelection;
    usageType: AuditUsageType | 'all' | '';
};

const INITIAL_FILTERS: FilterState = {
    appName: [],
    userId: null,
    userGroup: '',
    dateRange: null,
    feedback: '',
    sensitive_status: '',
    org: EMPTY_ORG_SELECTION,
    usageType: 'all',
};

// Daily chat, knowledge-space QA and channel-article QA all open the daily
// detail; their task-mode rows too (F003 AC-36).
const DAILY_FLOW_TYPES = [15, 20, 25, 30];
const USAGE_TYPES: AuditUsageType[] = ['daily', 'assistant', 'workflow', 'task'];
const usageTypeParam = (value?: string) => (value && value !== 'all' ? value as AuditUsageType : undefined);
const supportsAppFilter = (usageType: FilterState['usageType']) => usageType !== 'daily' && usageType !== 'task';

const appNameOf = (row, t) => (row.flow_type === 15 ? t('log.workbench_daily') : row.flow_name);
const usageTypeOf = (row, t) => (row.usage_type ? t(`log.usageType.${row.usage_type}`) : '');

// User candidates come from the audit scope, not the shared user directory (F003 decision 6).
const useSessionUsers = () => {
    const [options, setOptions] = useState<{ value: number, label: string }[]>([]);
    const load = (keyword = '') => {
        getAuditSessionUsersApi(keyword).then(res => setOptions(
            (res || []).filter(u => u.user_id != null).map(u => ({ value: u.user_id, label: u.user_name })),
        ));
    };
    return { options, load };
};

type Action =
    | { type: 'SET_FILTER'; payload: Partial<FilterState> }
    | { type: 'RESET' };

const filterReducer = (state: FilterState, action: Action): FilterState => {
    switch (action.type) {
        case 'SET_FILTER': {
            const next = { ...state, ...action.payload };
            return supportsAppFilter(next.usageType) ? next : { ...next, appName: [] };
        }
        case 'RESET':
            return { ...INITIAL_FILTERS };
        default:
            return state;
    }
};

export default function AppUseLog() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const paginationLocale = usePaginationLocale();
    const datePickerLocale = useDatePickerLocale();
    const selectLabels = useSelectLabels()
    const { appConfig } = useContext(locationContext)

    // 20 items per page
    const { page, pageSize, data: datalist, total, loading, loaded, setPage, filterData } = useTable({}, (param) => {
        return getAuditAppListApi({
            page: page,
            page_size: param.pageSize,
            flow_ids: param.appName?.length ? param.appName : undefined,
            user_ids: param.userId || undefined,
            group_ids: param.userGroup || undefined,
            ...getDateBounds(param.dateRange),
            feedback: param.feedback || undefined,
            sensitive_status: param.sensitive_status || undefined,
            org: param.org,
            usage_type: usageTypeParam(param.usageType),
        })
    });
    const sessionUsers = useSessionUsers();
    const processedData = useMemo(() =>
        datalist.map(el => ({
            ...el,
            userGroupsString: el.user_groups.map(item => item.name).join(','),
        })),
        [datalist] // Dependency: datalist
    );

    const [filters, dispatch] = useReducer(filterReducer, { ...INITIAL_FILTERS });
    const [dateError, setDateError] = useState<DatePickerError | null>(null);
    const [datePickerVersion, setDatePickerVersion] = useState(0);

    const resetClick = () => {
        dispatch({ type: 'RESET' });
        setDateError(null);
        setDatePickerVersion(version => version + 1);
        filterData({ ...INITIAL_FILTERS })
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

        const [startDay, endDay] = filters.dateRange ?? [null, null];
        const selectedStart = startDay ? parseISO(startDay) : null;
        const selectedEnd = endDay ? parseISO(endDay) : null;
        if (selectedStart && selectedEnd && differenceInCalendarDays(selectedEnd, selectedStart) >= 60) {
            toast.show({ type: 'error', message: t('log.exportDateRangeExceed') });
            return;
        }

        const exportEnd = selectedEnd ?? (selectedStart ? addDays(selectedStart, 59) : new Date());
        const exportStart = selectedStart ?? addDays(exportEnd, -59);
        const formattedStart = formatDate(exportStart, 'yyyy-MM-dd');
        const formattedEnd = formatDate(exportEnd, 'yyyy-MM-dd');
        if (!selectedStart || !selectedEnd) {
            const message = selectedStart || selectedEnd
                ? t('log.exportCustomDateRange', { start: formattedStart, end: formattedEnd })
                : t('log.exportNoDateRange');
            toast.show({ type: 'warning', message });
        }

        const { start_date, end_date } = getDateBounds([formattedStart, formattedEnd]);
        setAuditing(true);

        exportCsvDataApi({
            flow_ids: filters.appName?.length ? filters.appName : undefined,
            user_ids: filters.userId || undefined,
            group_ids: filters.userGroup || undefined,
            start_date,
            end_date,
            feedback: filters.feedback || undefined,
            sensitive_status: filters.sensitive_status || undefined,
            org: filters.org,
            usage_type: usageTypeParam(filters.usageType),
        }).then(async res => {
            const data = [
                [
                    t('log.csvHeaders.sessionId'),
                    t('log.csvHeaders.appName'),
                    t('log.csvHeaders.usageType'),
                    t('log.csvHeaders.sessionCreationTime'),
                    t('log.csvHeaders.userName'),
                    t('log.csvHeaders.org'),
                    t('log.csvHeaders.userGroup'),
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
                        appNameOf(item, t),
                        usageTypeOf(item, t),
                        item.create_time.replace('T', ' '),
                        item.user_name,
                        orgLabel(item.operator_dept_id, item.operator_dept_path, t),
                        // Join user group names with comma separator
                        (item.user_groups?.map((g: { name: string }) => g.name).join(',') ?? ''),
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


    return <div className="relative flex min-h-0 flex-1 flex-col">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className={`${styles.filterContainer} flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pt-2 pb-20`}>
            <div className={`${styles.filterGrid} shrink-0`}>
                <OrgFilter value={filters.org} onChange={(org) => dispatch({ type: 'SET_FILTER', payload: { org } })} />
                <Select
                    {...selectLabels}
                    allowClear
                    aria-label={t('log.usageType.label')}
                    placeholder={t('log.usageType.label')}
                    value={filters.usageType || null}
                    onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { usageType: value == null ? '' : value as AuditUsageType | 'all' } })}
                    options={[
                        { value: 'all', label: t('log.usageType.all') },
                        ...USAGE_TYPES.map(value => ({ value, label: t(`log.usageType.${value}`) })),
                    ]}
                />
                {supportsAppFilter(filters.usageType) && (
                    <FilterByApp value={filters.appName} placeholder={t('log.appName')} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { appName: value } })} />
                )}
                <Select
                    {...selectLabels}
                    allowClear
                    showSearch
                    aria-label={t('log.userName')}
                    placeholder={t('log.userName')}
                    options={sessionUsers.options}
                    value={filters.userId}
                    onOpenChange={(open) => { if (open) sessionUsers.load() }}
                    onSearch={sessionUsers.load}
                    onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { userId: value == null ? null : Number(value) } })}
                />
                <FilterByUsergroup value={filters.userGroup} placeholder={t('log.userGroup')} onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['userGroup']: value } })} />
                <DatePicker
                    key={datePickerVersion}
                    aria-label={t('datePicker.dateRange')}
                    className={styles.dateRange}
                    mode="range"
                    allowOpenRange
                    allowClear
                    value={filters.dateRange}
                    onChange={(dateRange: DatePickerOpenRange | null) => dispatch({ type: 'SET_FILTER', payload: { dateRange } })}
                    onValidationChange={setDateError}
                    locale={datePickerLocale}
                />
                <Select
                    {...selectLabels}
                    allowClear
                    aria-label={t('log.userFeedbackPlaceholder')}
                    placeholder={t('log.userFeedbackPlaceholder')}
                    value={filters.feedback || null}
                    onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['feedback']: value == null ? '' : String(value) } })}
                    options={[
                        { value: 'like', label: t('log.likeFeedback') },
                        { value: 'dislike', label: t('log.dislikeFeedback') },
                        { value: 'copied', label: t('log.copyFeedback') },
                    ]}
                />
                {appConfig.isPro && <Select
                    {...selectLabels}
                    allowClear
                    aria-label={t('log.sensitiveReviewResult')}
                    placeholder={t('log.sensitiveReviewResult')}
                    value={filters.sensitive_status || null}
                    onChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['sensitive_status']: value == null ? '' : String(value) } })}
                    options={[
                        { value: '2', label: t('log.sensitiveViolation') },
                        { value: '1', label: t('log.sensitivePass') },
                    ]}
                />}
                <div className={styles.filterActions}>
                    <Button onClick={resetClick} variant="outlined" color="default">{t('log.resetButton')}</Button>
                    <Button onClick={() => filterData(filters)} disabled={Boolean(dateError)}>{t('log.searchButton')}</Button>
                </div>
            </div>
            <Table containerClassName="shrink-0">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('log.appName')}</TableHead>
                        <TableHead>{t('log.usageType.label')}</TableHead>
                        <TableHead>{t('log.userName')}</TableHead>
                        <TableHead>{t('log.org.column')}</TableHead>
                        <TableHead>{t('log.userGroup')}</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead>{t('log.userFeedback')}</TableHead>
                        {appConfig.isPro && <TableHead>{t('log.sensitiveReviewResult')}</TableHead>}
                    </TableRow>
                </TableHeader>

                <TableBody>
                    {processedData.map((el: any) => {
                        const appName = supportsAppFilter(el.usage_type) ? appNameOf(el, t) : '--'
                        const usageType = usageTypeOf(el, t)
                        const createdAt = el.create_time.replace('T', ' ')
                        const detailPath = el.chat_id && (DAILY_FLOW_TYPES.includes(el.flow_type)
                            ? `/log/chatlog/${el.chat_id}`
                            : `/log/chatlog/${el.flow_id}/${el.chat_id}/${el.flow_type}`)

                        return <TableRow
                            key={el.id}
                            hoverable={Boolean(detailPath)}
                            className={detailPath ? 'cursor-pointer [&_.cursor-default]:cursor-pointer' : undefined}
                            onClick={detailPath ? (event) => {
                                if (event.defaultPrevented || (event.target as Element).closest('a')) return
                                handleCachePage()
                                navigate(detailPath)
                            } : undefined}
                        >
                            <TableCell className="font-medium max-w-[200px]">
                                {detailPath ? <Link
                                    to={detailPath}
                                    onClick={handleCachePage}
                                    aria-label={`${t('lib.details')} · ${appName && appName !== '--' ? appName : usageType} · ${createdAt}`}
                                    className="truncate-multiline rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
                                >{appName}</Link> : <div className="truncate-multiline">{appName}</div>}
                            </TableCell>
                            <TableCell>{usageType}</TableCell>
                            <TableCell>{el.user_name}</TableCell>
                            <TableCell className="max-w-[200px]">
                                <OrgPathText text={orgLabel(el.operator_dept_id, el.operator_dept_path, t)} />
                            </TableCell>
                            <TableCell>{el.userGroupsString}</TableCell>
                            <TableCell>{createdAt}</TableCell>
                            <TableCell>
                                <div className="flex items-center gap-2 text-xs">
                                    <div className="flex flex-col items-center">
                                        <Outlined.ThumbsUp
                                            size={16} aria-hidden
                                            className={el.like_count ? 'text-primary' : 'text-gray-400'}
                                        />
                                        <span>{el.like_count}</span>
                                    </div>
                                    <div className="flex flex-col items-center">
                                        <Outlined.ThumbsDown
                                            size={16} aria-hidden
                                            className={el.dislike_count ? 'text-primary' : 'text-gray-400'}
                                        />
                                        <span>{el.dislike_count}</span>
                                    </div>
                                    <div className="flex flex-col items-center">
                                        <Outlined.Copy
                                            size={16} aria-hidden
                                            className={el.copied_count ? 'text-primary' : 'text-gray-400'}
                                        />
                                        <span>{el.copied_count}</span>
                                    </div>
                                </div>
                            </TableCell>
                            {appConfig.isPro && <TableCell>
                                {el.sensitive_status === 1 ? <Tag size="small" dot color="success" className="whitespace-nowrap shrink-0">{t('log.sensitivePass')}</Tag>
                                    : <Tag size="small" dot color="danger" className="whitespace-nowrap shrink-0">{t('log.sensitiveViolation')}</Tag>
                                }
                            </TableCell>}
                        </TableRow>
                    })}
                </TableBody>
            </Table>
            {loaded && !loading && processedData.length === 0 && <AuditEmptyState />}
        </div>
        <div className="bisheng-table-footer gap-4 pl-2 pr-6 bg-background-login">
            <Button className="shrink-0" onClick={handleExport} loading={auditing} disabled={auditing || Boolean(dateError)}>
                {t('log.exportButton')}
            </Button>
            <Pagination locale={paginationLocale}
                className="ml-auto min-w-0"
                current={page}
                pageSize={pageSize}
                total={total}
                showTotal={true}
                onChange={(newPage) => setPage(newPage)}
            />
        </div>
    </div>
};
