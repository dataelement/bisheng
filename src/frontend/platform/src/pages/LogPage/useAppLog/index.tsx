
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
            sensitive_status: param.sensitive_status || undefined,
        })
    });
    const processedData = useMemo(() =>
        datalist.map(el => ({
            ...el,
            userGroupsString: el.user_groups.map(item => item.name).join(','),
        })),
        [datalist] // 依赖 datalist
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
        const [start_date, end_date] = getStrTime([adjustedStart, adjustedEnd])

        exportCsvDataApi({
            flow_ids: filters.appName?.length ? filters.appName.map(el => el.value) : undefined,
            user_ids: filters.userName?.[0]?.value || undefined,
            group_ids: filters.userGroup || undefined,
            start_date,
            end_date,
            feedback: filters.feedback || undefined,
            sensitive_status: filters.sensitive_status || undefined,
        }).then(async res => {
            const data = [
                ['会话ID', '应用名称', '会话创建时间', '用户名称', '消息角色', '消息发送时间', '消息文本内容', '点赞', '点踩', '复制', '是否命中内容安全审查']
            ];

            const handleMessage = (msg, category, id) => {
                try {
                    msg = msg && msg[0] === '{' ? JSON.parse(msg) : msg || ''
                } catch (error) {
                    console.error('error :>> ', `${id} 消息转换失败`);
                }
                // output
                if ('output_with_input_msg' === category) return `${msg.msg} :${msg.hisValue}`
                if ('output_with_choose_msg' === category) return `${msg.msg} :${msg.options.find(el => el.id === msg.hisValue)?.label}`
                return typeof msg === 'string' ? msg : (msg.input || msg.msg)
            }

            // 数据转换
            res.data.forEach(item => {
                item.messages.forEach(msg => {
                    const { message, category } = msg
                    const usefulMsg = !['flow', 'tool_call', 'tool_result'].includes(category) && message
                    usefulMsg && data.push([
                        item.chat_id,
                        item.flow_name,
                        item.create_time.replace('T', ' '),
                        item.user_name,
                        msg.is_bot ? 'AI' : '用户',
                        msg.create_time.replace('T', ' '),
                        handleMessage(message, msg.category, item.flow_id + '_' + item.chat_id),
                        msg.liked === 1 ? '是' : '否',
                        msg.liked === 2 ? '是' : '否',
                        msg.copied ? '是' : '否',
                        msg.sensitive_status === 1 ? '否' : '是'
                    ])
                })
            })
            // 导出excle
            const fileName = generateFileName(start_date, end_date, user.user_name);
            exportCsv(data, fileName, true)

            // await downloadFile(__APP_ENV__.BASE_URL + res.url, fileName);
            setAuditing(false);
        }).catch((error) => {
            setAuditing(false);
            // 可选：处理错误情况
        });
    };


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
                    <Select value={filters.sensitive_status} onValueChange={(value) => dispatch({ type: 'SET_FILTER', payload: { ['sensitive_status']: value } })} >
                        <SelectTrigger className="w-[200px]">
                            <SelectValue placeholder="实时内容安全审查结果" />
                        </SelectTrigger>
                        <SelectContent className="max-w-[200px] break-all">
                            <SelectGroup>
                                <SelectItem value={'2'}>违规</SelectItem>
                                <SelectItem value={'1'}>通过</SelectItem>
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
                }} >查询</Button>
                <Button onClick={resetClick} variant="outline">重置</Button>
                <Button onClick={handleExport} disabled={auditing}>
                    {auditing && <LoadIcon className="mr-1" />}导出</Button>
            </div>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('log.appName')}</TableHead>
                        <TableHead>{t('log.userName')}</TableHead>
                        <TableHead>用户组</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead>{t('log.userFeedback')}</TableHead>
                        {appConfig.isPro && <TableHead>实时内容安全审查结果</TableHead>}
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>

                <TableBody>
                    {processedData.map((el: any) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium max-w-[200px]">
                                <div className=" truncate-multiline">{el.flow_name}</div>
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
                                {el.sensitive_status === 1 ? <Badge variant="outline" className="text-green-500">通过</Badge>
                                    : <Badge variant="outline" className="text-red-500">违规</Badge>
                                }
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
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
    </div>
};
