import { useRef, useEffect, useCallback, useMemo, useContext, useState } from "react";
import { copyText } from "../utils";
import { alertContext } from "../contexts/alertContext";
import { useTranslation } from "react-i18next";

// 防抖
export function useDebounce(func: any, wait: number, immediate: boolean, callback?: any,): (any?: any) => any {
    let timer = useRef<NodeJS.Timeout | null>();
    const fnRef = useRef<any>(func);
    useEffect(() => { fnRef.current = func; }, [func]);
    const timerCancel = function () { if (timer.current) clearTimeout(timer.current); };

    function debounced(...args: any[]) {
        const runFunction = () => {
            return callback
                ? callback(fnRef.current.apply(fnRef.current, args))
                : fnRef.current.apply(fnRef.current, args);
        };
        timerCancel();
        if (immediate) {
            let runNow = !timer.current;
            timer.current = setTimeout(() => { timer.current = null; }, wait);
            if (runNow) {
                runFunction();
            }
        } else {
            timer.current = setTimeout(() => { runFunction(); }, wait);
        }
    }
    debounced.cancel = function () { timerCancel(); timer.current = null; };
    return useCallback(debounced, [wait, immediate, timerCancel, func]);
}

export function useHasForm(flow) {
    return useMemo(() => {
        // 如果有 VariableNode  inputnode 就属于
        return !!flow?.data?.nodes.find(node => ["VariableNode", "InputFileNode"].includes(node.data.type))
    }, [flow])
}

export function useHasReport(flow) {
    return useMemo(() =>
        !!flow?.data?.nodes.find(node => "Report" === node.data.type)
        , [flow])
}

// 复制文案
export function useCopyText() {
    const { t } = useTranslation()
    const { setSuccessData } = useContext(alertContext);
    return (url) => {
        copyText(url).then(() =>
            setSuccessData({ title: t('chat.copyTip') })
        )
    }
}

// 表格通用逻辑（分页展示、表格数据、关键词检索）
export function useTable(apiFun) {

    const [page, setPage] = useState({
        page: 1,
        pageSize: 20,
        keyword: "",
    });
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState([]);

    const paramRef = useRef({});

    const requestIdRef = useRef(0); // 控制请求响应顺序
    const loadData = () => {
        setLoading(true);
        const requestId = ++requestIdRef.current
        apiFun({ ...page, ...paramRef.current }).then(res => {
            if (requestId !== requestIdRef.current) return
            setData(res.data);
            setTotal(res.total);
            setLoading(false);
        }).catch(() => {
            setLoading(false);
        })
    }
    const debounceLoad = useDebounce(loadData, 600, false)

    useEffect(() => {
        debounceLoad();
    }, [page])

    return {
        page: page.page,
        pageSize: page.pageSize,
        total,
        loading,
        data,
        setPage: (p) => setPage({ ...page, page: p }),
        reload: debounceLoad,
        // 检索
        search: useDebounce((keyword) => {
            setPage({ ...page, page: 1, keyword });
        }, 100, false),
        // 数据过滤
        filterData: (p) => {
            paramRef.current = { ...paramRef.current, ...p };
            debounceLoad()
        },
        // 更新数据
        refreshData: (compareFn, data) => {
            // 乐观更新
            setData(list => {
                return list.map(item => compareFn(item) ? { ...item, ...data } : item)
            })
        }
    }
}
