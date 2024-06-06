import clsx, { ClassValue } from "clsx";
import { useCallback, useEffect, useRef } from "react";
import { twMerge } from "tailwind-merge";

/**
 * 样式合并
 */
export function cname(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}


export const generateUUID = (length: number) => {
  let d = new Date().getTime()
  const uuid = ''.padStart(length, 'x').replace(/[xy]/g, (c) => {
    const r = (d + Math.random() * 16) % 16 | 0
    d = Math.floor(d / 16)
    return (c == 'x' ? r : (r & 0x7 | 0x8)).toString(16)
  })
  return uuid
}


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

