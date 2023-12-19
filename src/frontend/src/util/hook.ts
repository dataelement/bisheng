import { useRef, useEffect, useCallback } from "react";

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
