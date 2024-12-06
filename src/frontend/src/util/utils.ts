import axios from "axios";
import clsx, { ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { APITemplateType } from "../types/api";
import { checkUpperWords } from "../utils";

export function classNames(...classes: Array<string>): string {
    return classes.filter(Boolean).join(" ");
}

export function downloadFile(url, label) {
    console.log('download file :>> ', url);

    return axios.get(url, { responseType: "blob" }).then((res: any) => {
        const blob = new Blob([res.data]);
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = label;
        link.click();
        URL.revokeObjectURL(link.href);
    }).catch(console.error);
}

export function downloadJson(content) {
    const jsonStr = JSON.stringify(content)
    const jsonString = `data:text/json;chatset=utf-8,${encodeURIComponent(jsonStr)}`;

    const link = document.createElement("a");
    link.href = jsonString;
    link.download = `sample.json`;

    link.click();
}

export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs));
}

// 交集
export function intersectArrays(...arrays) {
    if (arrays.length === 0) {
        return [];
    }

    // 使用第一个数组作为基准
    const baseArray = arrays[0];

    // 过滤出基准数组中的元素，这些元素在其他所有数组中都存在
    const intersection = baseArray.filter((element) => {
        return arrays.every((array) => array.includes(element));
    });

    return intersection;
}

// 时间戳转换 天时分秒（dhms）
export function formatMilliseconds(ms: number, format: string): string {
    const secondsInMillisecond = 1;
    const minutesInMillisecond = secondsInMillisecond * 60;
    const hoursInMillisecond = minutesInMillisecond * 60;
    const daysInMillisecond = hoursInMillisecond * 24;

    const days = Math.floor(ms / daysInMillisecond);
    const remainingHours = ms % daysInMillisecond;
    const hours = Math.floor(remainingHours / hoursInMillisecond);
    const remainingMinutes = remainingHours % hoursInMillisecond;
    const minutes = Math.floor(remainingMinutes / minutesInMillisecond);
    const remainingSeconds = remainingMinutes % minutesInMillisecond;
    const seconds = Math.floor(remainingSeconds / secondsInMillisecond);

    let formattedString = format.replace('dd', days.toString());
    formattedString = formattedString.replace('hh', hours.toString());
    formattedString = formattedString.replace('mm', minutes.toString());
    formattedString = formattedString.replace('ss', seconds.toString());

    // Remove any extra spaces
    // formattedString = formattedString.replace(/\s+/g, ' ').trim();

    return formattedString;
}

// Date转换为目标格式
export function formatDate(date: Date, format: string): string {
    const addZero = (num) => num < 10 ? `0${num}` : `${num}`
    const replacements = {
        'yyyy': date.getFullYear(),
        'MM': addZero(date.getMonth() + 1),
        'dd': addZero(date.getDate()),
        'HH': addZero(date.getHours()),
        'mm': addZero(date.getMinutes()),
        'ss': addZero(date.getSeconds())
    }
    return format.replace(/yyyy|MM|dd|HH|mm|ss/g, (match) => replacements[match])
}

// param time: yyyy-mm-ddTxxxx
export function formatStrTime(time: string, notSameDayFormat: string): string {
    if (!time) return ''
    const date1 = new Date(time)
    const date2 = new Date()
    return date1.getFullYear() === date2.getFullYear() &&
        date1.getMonth() === date2.getMonth() &&
        date1.getDate() === date2.getDate() ? formatDate(date1, 'HH:mm') : formatDate(date1, notSameDayFormat)
}

export function toTitleCase(str: string | undefined): string {
    if (!str) return "";
    let result = str
        .split("_")
        .map((word, index) => {
            if (index === 0) {
                return checkUpperWords(
                    word[0].toUpperCase() + word.slice(1).toLowerCase()
                );
            }
            return checkUpperWords(word.toLowerCase());
        })
        .join(" ");

    return result
        .split("-")
        .map((word, index) => {
            if (index === 0) {
                return checkUpperWords(
                    word[0].toUpperCase() + word.slice(1).toLowerCase()
                );
            }
            return checkUpperWords(word.toLowerCase());
        })
        .join(" ");
}

export function getFieldTitle(
    template: APITemplateType,
    templateField: string
): string {
    return template[templateField].display_name
        ? template[templateField].display_name!
        : template[templateField].name
            ? toTitleCase(template[templateField].name!)
            : toTitleCase(templateField);
}
