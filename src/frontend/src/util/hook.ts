import { useRef, useEffect, useCallback, useMemo, useContext } from "react";
import { copyText } from "../utils";
import { alertContext } from "../contexts/alertContext";
import { useTranslation } from "react-i18next";

export function useDebounce(func: any, wait: number, immediate: boolean, callback?: any,): any {
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