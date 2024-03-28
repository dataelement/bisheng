import clsx, { ClassValue } from "clsx";
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