import { useRef, useEffect, useCallback, useMemo, useContext, useState } from "react";
import { copyText } from "../utils";
import { alertContext } from "../contexts/alertContext";
import { useTranslation } from "react-i18next";
import cloneDeep from "lodash-es/cloneDeep";

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
export function useTable<T extends object>(param, apiFun) {
    const unInitDataRef = useRef(!!param.unInitData);

    const cancelLoadingWhenReload = param.cancelLoadingWhenReload || false;
    const [page, setPage] = useState({
        page: 1,
        pageSize: param.pageSize || 20,
        keyword: "",
    });
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState<T[]>([]);
    const [loaded, setLoaded] = useState(false);

    const paramRef = useRef({});

    const requestIdRef = useRef(0); // 控制请求响应顺序
    const loadData = () => {
        !cancelLoadingWhenReload && setLoading(true);
        const requestId = ++requestIdRef.current
        apiFun({ ...page, ...paramRef.current }).then(res => {
            console.log('res :>> ', res);
            if (requestId !== requestIdRef.current) return
            if (!("total" in res)) return console.error('该接口不支持分页，无法正常使用 useTable')
            setData(res.data);
            setTotal(res.total);
            setLoading(false);
        }).catch(() => {
            setLoading(false);
        })

        setLoaded(true);
    }
    const debounceLoad = useDebounce(loadData, 600, false)

    // 记录旧值
    const prevValueRef = useRef(page);

    useEffect(() => {
        if (unInitDataRef.current) return;
        // 排除页码防抖
        prevValueRef.current.page === page.page ? debounceLoad() : loadData()
        prevValueRef.current = page
    }, [page])

    return {
        page: page.page,
        pageSize: page.pageSize,
        total,
        loaded,
        loading,
        data,
        setPage: (p) => setPage({ ...page, page: p }),
        reload: debounceLoad,
        // 检索
        search: (keyword) => {
            unInitDataRef.current = false;
            setPage({ ...page, page: 1, keyword });
        },
        // 数据过滤
        filterData: (p) => {
            unInitDataRef.current = false;
            paramRef.current = { ...paramRef.current, ...p };
            page.page === 1 ? loadData() : setPage({ ...page, page: 1 });
        },
        // 更新数据
        refreshData: (compareFn, data) => {
            // 乐观更新
            setData(list => {
                return list.map(item => compareFn(item) ? { ...item, ...data } : item)
            })
        },
        clean: () => {
            unInitDataRef.current = !!param.unInitData;
            setPage({
                page: 1,
                pageSize: param.pageSize || 20,
                keyword: "",
            })
            paramRef.current = {}
            setTotal(0)
            setData([])
            setLoaded(false)
        }
    }
}

/**
 * 复制粘贴
 * @param dom 事件绑定 dom
 * @param lastSelection 被复制对象
 * @param paste 粘贴时间回调，参数（克隆的lastSelection，鼠标当前坐标）
 * @param deps 依赖
 */
export function useCopyPaste(dom, lastSelection, paste, deps) {
    const position = useRef({ x: 0, y: 0 });
    const [lastCopiedSelection, setLastCopiedSelection] = useState(null);

    useEffect(() => {
        if (!dom) return
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.target.tagName === 'INPUT') return // 排除输入框内复制粘贴

            if (
                (event.ctrlKey || event.metaKey) &&
                event.key === "c" &&
                lastSelection
            ) {
                event.preventDefault();
                setLastCopiedSelection(cloneDeep(lastSelection));
            } else if (
                (event.ctrlKey || event.metaKey) &&
                event.key === "v" &&
                lastCopiedSelection
            ) {
                event.preventDefault();
                paste(lastCopiedSelection, position.current)
            } else if (
                (event.ctrlKey || event.metaKey) &&
                event.key === "g" &&
                lastSelection
            ) {
                event.preventDefault();
            }
        };
        const handleMouseMove = (event) => {
            position.current = { x: event.clientX, y: event.clientY };
        };

        dom.addEventListener("keydown", onKeyDown);
        dom.addEventListener("mousemove", handleMouseMove);

        return () => {
            dom?.removeEventListener("keydown", onKeyDown);
            dom?.removeEventListener("mousemove", handleMouseMove);
        };
    }, [dom, lastSelection, lastCopiedSelection, ...deps]);
}

// undo redo
export function useUndoRedo<T>(data, undoCall, redoCall, maxHistorySize = 100) {
    const [past, setPast] = useState<T[]>([]); // 过去的历史记录（past）
    const [future, setFuture] = useState<T[]>([]); // 和未来的历史记录（future)
    /**
     * 快照功能
     * 将上一次的状态保存到 past 中，并清空 future
     * if max = 2: [1,x,x] -> [x, x]
     * [x,x,new]
     */
    const takeSnapshot = useCallback((data: T) => {
        setPast((old) => {
            // let newPast = cloneDeep(old);
            const newPast = old.slice(
                old.length - maxHistorySize + 1,
                old.length
            );
            newPast.push(data);
            return newPast;
        });
        setFuture([]);
    }, [setPast, setFuture]);
    /**
     * 撤销
     * 将状态恢复到 past 中的上一个状态，并将当前状态保存到 future 中
     * past [x,x,x,del]
     * future [x,x,x,add当前]
     * undoCall(del)
     */
    const undo = useCallback(() => {
        const pastState = past[past.length - 1];

        if (pastState) {
            setPast((old) => {
                // let newPast = cloneDeep(old);
                let newPast = old.slice(0, old.length - 1);
                return newPast;
            });
            setFuture((old) => {
                // let newFuture = cloneDeep(old);
                let newFuture = old;
                newFuture.push(data);
                return newFuture;
            });
            undoCall(pastState)
        }
    }, [data, past, setFuture, setPast, undoCall]);
    /**
     * 重做
     * 将状态恢复到 future 中的下一个状态，并将当前状态保存到 past 中
     * past [x,x,x,add当前]
     * future [x,x,x,del]
     * redoCall(del)
     */
    const redo = useCallback(() => {
        const futureState = future[future.length - 1];

        if (futureState) {
            setFuture((old) => {
                // let newFuture = cloneDeep(old);
                let newFuture = old.slice(0, old.length - 1);
                return newFuture;
            });
            setPast((old) => {
                // let newPast = cloneDeep(old);
                let newPast = old
                newPast.push(data);
                return newPast;
            });
            redoCall(futureState)
        }
    }, [data, future, setFuture, setPast, redoCall]);

    // 快捷键
    useEffect(() => {
        const keyDownHandler = (event: KeyboardEvent) => {
            if (event.key === "z" && (event.ctrlKey || event.metaKey) && event.shiftKey) {
                redo();
            } else if (event.key === "y" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                redo();
            } else if (event.key === "z" && (event.ctrlKey || event.metaKey)) {
                undo();
            }
        };

        document.addEventListener("keydown", keyDownHandler);
        return () => document.removeEventListener("keydown", keyDownHandler);
    }, [undo, redo]);

    return {
        clean: () => { setPast([]); setFuture([]) },
        takeSnapshot
    }
}