import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import React, { useMemo } from 'react';
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
        <Tabs defaultValue={data.tab.value} className="w-full px-3" onValueChange={onChange}>
            <TabsList className="w-full flex">
                {processedOptions.map(option => (
                    <TabsTrigger className="flex-1" key={option.key} value={option.key}>
                        {t(`node.${data.type}.tab_${option.key}.label`)}
                        {option.processedHelp && (
                            <QuestionTooltip content={t(`node.${data.type}.tab_${option.key}.help`)} />
                        )}
                    </TabsTrigger>
                ))}
            </TabsList>
        </Tabs>
    );
}
