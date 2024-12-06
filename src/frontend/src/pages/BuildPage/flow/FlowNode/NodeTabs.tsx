import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import React, { useMemo } from 'react';

export default function NodeTabs({ data, onChange }) {
    const processHelpContent = (help) => {
        // 检查是否有 !(xxx) 格式的内容
        const regex = /(.*?)!\((.*?)\)(.*)/;
        const match = help.match(regex);

        const images = {
            "input": "/tabImages/input-demo.jpeg",
            "form": "/tabImages/form-demo.jpeg"
        }

        if (match) {
            const [, before, imgSrc, after] = match;
            return (
                <>
                    {before}
                    <img className="w-60 rounded-sm" src={images[imgSrc]} alt="tooltip" />
                    {after}
                </>
            );
        }
        return help;
    };

    const processedOptions = useMemo(() => {
        return data.options.map(option => ({
            ...option,
            processedHelp: option.help ? processHelpContent(option.help) : null,
        }));
    }, [data.options]);

    return (
        <Tabs defaultValue={data.value} className="w-full px-3" onValueChange={onChange}>
            <TabsList className="w-full flex">
                {processedOptions.map(option => (
                    <TabsTrigger className="flex-1" key={option.key} value={option.key}>
                        {option.label}
                        {option.processedHelp && (
                            <QuestionTooltip content={option.processedHelp} />
                        )}
                    </TabsTrigger>
                ))}
            </TabsList>
        </Tabs>
    );
}
