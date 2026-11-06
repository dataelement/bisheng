// @ts-strict-ignore
import { Tabs,Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useMemo } from 'react';
import { useTranslation } from "react-i18next";

export default function NodeTabs({ data, onChange }) {
    const { t } = useTranslation('flow')
    const processHelpContent = (help) => {
        // 检查是否有 !(xxx) 格式的内容
        const regex = /(.*?)!\((.*?)\)(.*)/;
        const match = help.match(regex);

        const images = {
            "input": "/assets/tabImages/input-demo.jpeg",
            "form": "/assets/tabImages/form-demo.jpeg"
        }

        if (match) {
            const [, before, imgSrc, after] = match;
            return (
                <>
                    {before}
                    <img className="w-60 rounded-sm" src={__APP_ENV__.BASE_URL + images[imgSrc]} alt="tooltip" />
                    {after}
                </>
            );
        }
        return help;
    };

    const processedOptions = useMemo(() => {
        return data.tab.options.map(option => ({
            ...option,
            processedHelp: option.help ? processHelpContent(option.help) : null,
        }));
    }, [data.tab.options]);

    return (
        <Tabs defaultActiveKey={data.tab.value} className="w-full px-3" onChange={onChange}
            items={processedOptions.map(option => ({
                key: option.key,
                label: <span className="inline-flex items-center gap-1">
                    {t(`node.${data.type}.tab_${option.key}.label`)}
                    {option.processedHelp && <Tooltip content={t(`node.${data.type}.tab_${option.key}.help`)}>
                        <span className="inline-flex"><Outlined.Question size={14} className="text-text-3" /></span>
                    </Tooltip>}
                </span>,
            }))} />
    );
}
