import axios from "axios";
import clsx, { ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function classNames(...classes: Array<string>): string {
    return classes.filter(Boolean).join(" ");
}

export function downloadFile(url, label) {
    axios.get(url, { responseType: "blob" }).then(response => {
        const blob = new Blob([response.data]);
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = label;
        link.click();
        URL.revokeObjectURL(link.href);
    }).catch(console.error);
}

export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs));
}