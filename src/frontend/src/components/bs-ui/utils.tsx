import clsx, { ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * 样式合并
 */
export function cname(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}