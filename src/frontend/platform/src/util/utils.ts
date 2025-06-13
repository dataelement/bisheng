import axios from "axios";
import clsx, { ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import * as XLSX from 'xlsx';
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

/**
 * 修复字符串中的不完整 Unicode 代理对（如单独的 \ud83d、\ud83c）
 * @param {string} text - 原始字符串
 * @returns {string} - 修复后的字符串
 */
function fixBrokenEmojis(text) {
    return text.replace(
        // 匹配单独的高位代理（\ud800-\udbff）且后面不跟低位代理（\udc00-\udfff）
        /([\ud800-\udbff])(?![\udc00-\udfff])/g,
        // 替换为完整的“问号”表情（或其他默认字符）
        (highSurrogate) => highSurrogate + '\udfff' // 组合成合法但无意义的字符
    );
}

export function exportCsv(
    data: any[],
    fileName: string = 'test_result.csv',
    useBase64: boolean = false // 默认使用 Blob 方式
) {
    // 处理数据
    const newData = data.map(row =>
        row.map(cell => typeof cell === 'string' ? fixBrokenEmojis(cell) : cell)
    );

    // 创建 Worksheet
    const ws = XLSX.utils.aoa_to_sheet(newData);
    const csv = XLSX.utils.sheet_to_csv(ws);

    if (useBase64) {
        // 处理Unicode字符并转换为Base64
        const base64String = btoa(unescape(encodeURIComponent(csv)));
        // 创建Data URL（使用base64编码避免URL编码问题）
        const csvContent = `data:text/csv;charset=utf-8;base64,${base64String}`;

        const a = document.createElement("a");
        a.href = csvContent;
        // a.href = url;
        a.download = fileName;

        // 模拟点击下载链接
        document.body.appendChild(a);
        a.click();

        // 清理URL对象
        setTimeout(function () {
            document.body.removeChild(a);
            // window.URL.revokeObjectURL(url);
        }, 0);
    } else {
        // 创建Workbook对象
        const wb = XLSX.utils.book_new();
        // 添加Worksheet到Workbook中
        XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
        // 生成Excel文件
        const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
        const blob = new Blob([wbout], { type: 'application/octet-stream' });
        // 创建下载链接
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "test_result.xlsx";

        // 模拟点击下载链接
        document.body.appendChild(a);
        a.click();

        // 清理URL对象
        setTimeout(function () {
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }, 0);
    }
}

// 校验合法json
export function isValidJSON(str) {
    if (typeof str !== 'string') return false;

    // 简单的前置检查
    str = str.trim();
    if (!(str.startsWith('{') && str.endsWith('}')) &&
        !(str.startsWith('[') && str.endsWith(']'))) {
        return false;
    }

    // 完整解析验证
    try {
        JSON.parse(str);
        return true;
    } catch (e) {
        return false;
    }
}

// 取后缀名
export function getFileExtension(filename) {
    const basename = filename.split(/[\\/]/).pop(); // 去除路径
    const match = basename.match(/\.([^.]+)$/);
    return (match ? match[1] : '').toUpperCase();
}


/**
 * 截取字符串并在末尾添加省略号（如果需要）
 * @param {string} str - 要处理的字符串
 * @param {number} maxLength - 最大允许长度
 * @returns {string} 处理后的字符串
 */
export function truncateString(str, maxLength) {
    // 检查输入是否有效
    if (typeof str !== 'string' || typeof maxLength !== 'number' || maxLength < 0) {
        return str;
    }

    // 如果字符串长度不超过最大长度，直接返回原字符串
    if (str.length <= maxLength) {
        return str;
    }

    // 截取字符串并添加省略号
    return str.substring(0, maxLength) + '...';
}