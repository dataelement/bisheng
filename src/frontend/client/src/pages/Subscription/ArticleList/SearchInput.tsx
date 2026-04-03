import { useLocalize } from "~/hooks";
import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface SearchInputProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    className?: string;
}

export function SearchInput({
    value,
    onChange,
    placeholder,
    className
}: SearchInputProps) {
    const localize = useLocalize();
    const [isActive, setIsActive] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (isActive && inputRef.current) {
            inputRef.current.focus();
        }
    }, [isActive]);

    const handleBlur = () => {
        if (!value) {
            setIsActive(false);
        }
    };

    return (
        <div
            className={`group relative flex items-center h-8 border border-gray-100 rounded-md ${isActive ? "w-[240px]" : "w-8 cursor-pointer"
                } ${className || ""}`}
            style={{
                transitionProperty: 'background-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out'
            }}
            onClick={() => !isActive && setIsActive(true)}
        >
            <div className={`absolute flex items-center justify-center ${isActive ? "left-2.5" : "left-[7px]"
                }`}
                style={{
                    transitionProperty: 'background-color',
                    transitionDuration: '350ms',
                    transitionTimingFunction: 'ease-in-out'
                }}
            >
                <Search className="size-4 text-gray-500" />
            </div>

            <input
                ref={inputRef}
                className={`w-full h-full bg-transparent pl-9 pr-8 text-[14px] outline-none  ${isActive ? "opacity-100" : "opacity-0 pointer-events-none"
                    }`}
                style={{
                    transitionProperty: 'background-color',
                    transitionDuration: '350ms',
                    transitionTimingFunction: 'ease-in-out'
                }}
                placeholder={placeholder ?? localize("com_subscription.search")}
                maxLength={100}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onBlur={handleBlur}
            />
        </div>
    );
}