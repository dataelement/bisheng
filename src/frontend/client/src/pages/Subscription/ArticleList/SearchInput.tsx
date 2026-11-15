import { ExpandableSearchField } from "~/components/ui/ExpandableSearchField";
import { useLocalize, useMediaQuery } from "~/hooks";

interface SearchInputProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    fullWidth?: boolean;
}

/** 订阅文章列表工具栏搜索：与消息提醒弹窗同一套展开搜索交互与样式 */
export function SearchInput({ value, onChange, placeholder, fullWidth = false }: SearchInputProps) {
    const localize = useLocalize();
    const isCompactViewport = useMediaQuery("(max-width: 768px)");

    return (
        <ExpandableSearchField
            value={value}
            onChange={onChange}
            placeholder={placeholder ?? localize("com_subscription.search")}
            titleWhenCollapsed={placeholder ?? localize("com_subscription.search")}
            expandedWidthClassName={fullWidth ? "w-full" : "w-[220px]"}
            containerClassName="min-w-0 max-w-full [&:not(:focus-within)]:border-border-base"
            alwaysExpanded={fullWidth || isCompactViewport}
            maxLength={100}
        />
    );
}
