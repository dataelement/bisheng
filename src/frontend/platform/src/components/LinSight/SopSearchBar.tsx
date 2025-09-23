import { Search } from "lucide-react";
import { useEffect } from "react";
import { useDebounce } from "@/util/hook";

interface SopSearchBarProps {
    value: string;
    placeholder: string;
    onChangeValue: (v: string) => void;
    onSearch: (v: string) => void;
    debounceMs?: number;
    debounceKey?: any;
}

export default function SopSearchBar({ value, placeholder, onChangeValue, onSearch, debounceMs = 500, debounceKey }: SopSearchBarProps) {
    const debouncedSearch = useDebounce((v: string) => onSearch(v), debounceMs, false);

    useEffect(() => {
        return () => {
            (debouncedSearch as any)?.cancel?.();
        }
    }, []);

    useEffect(() => {
        // 当外部依赖变化时，取消上一次定时，使用新的防抖周期
        (debouncedSearch as any)?.cancel?.();
    }, [debounceKey]);

    return (
        <div className="relative flex-1 max-w-xs">
            <div className="relative">
                <input
                    type="text"
                    placeholder={placeholder}
                    className="w-full pl-10 pr-3 py-1.5 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    value={value}
                    onChange={(e) => {
                        const newValue = e.target.value;
                        onChangeValue(newValue);
                        debouncedSearch(newValue);
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            (debouncedSearch as any)?.cancel?.();
                            onSearch(value);
                        }
                    }}
                />
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            </div>
        </div>
    );
}


