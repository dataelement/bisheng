import { ExpandableSearchField } from "~/components/ui/ExpandableSearchField";
import { useLocalize, useMediaQuery } from "~/hooks";

interface SearchInputProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    className?: string;
}

/** 订阅文章列表工具栏搜索：与消息提醒弹窗同一套展开搜索交互与样式 */
export function SearchInput({ value, onChange, placeholder, className }: SearchInputProps) {
    const localize = useLocalize();
    const isMobileOrTablet = useMediaQuery("(max-width: 768px)");

    return (
        <ExpandableSearchField
            value={value}
            onChange={onChange}
            placeholder={placeholder ?? localize("com_subscription.search")}
            titleWhenCollapsed={placeholder ?? localize("com_subscription.search")}
            containerClassName={className}
            alwaysExpanded={isMobileOrTablet}
            containerClassName={className}
            alwaysExpanded={isMobileOrTablet}
            maxLength={100}
        />
    );
}
