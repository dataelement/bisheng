import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { SettingIcon } from "@/components/bs-icons/setting";
import { ToolIcon } from "@/components/bs-icons/tool";
import {
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/bs-ui/accordion";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { useTranslation } from "react-i18next";

export default function ToolItem({
    type,
    select,
    data,
    onEdit = (id) => { },
    onSelect,
    onSetClick = null
}) {
    const { t } = useTranslation();

    return <AccordionItem key={data.id} value={data.id} className="data-[state=open]:border-2 data-[state=open]:border-primary/20 data-[state=open]:rounded-md">
        <AccordionTrigger>
            <div className="group w-full flex gap-2 text-start relative pr-4">
                <TitleIconBg className="w-8 h-8 min-w-8" id={data.id} ><ToolIcon /></TitleIconBg>
                <div className="flex-1 min-w-0">
                    <div className="w-full text-sm font-medium leading-none flex items-center gap-2">{data.name}
                        {
                            type === 'edit' && <div
                                className="group-hover:opacity-100 opacity-0 hover:bg-[#EAEDF3] rounded cursor-pointer"
                                onClick={(e) => onEdit(data.id)}
                            ><SettingIcon /></div>
                        }
                        {
                            onSetClick && <div
                                className="group-hover:opacity-100 opacity-0 hover:bg-[#EAEDF3] rounded cursor-pointer"
                                onClick={onSetClick}
                            ><SettingIcon /></div>
                        }
                    </div>
                    <p className="text-sm text-muted-foreground mt-2">{data.description}</p>
                </div>
            </div>
        </AccordionTrigger>
        <AccordionContent className="">
            <div className="px-6 mb-4">
                {data.children.map(api => (
                    <div key={api.name} className="relative p-4 rounded-sm  border-t">
                        <h1 className="text-sm font-medium leading-none">{api.name}</h1>
                        <p className="text-sm text-muted-foreground mt-2">{api.desc}</p>
                        {
                            api.api_params?.length > 0 && <p className="text-sm text-muted-foreground mt-2 flex gap-2">
                                <TooltipProvider>
                                    <Tooltip delayDuration={100}>
                                        <TooltipTrigger asChild>
                                            <span className="text-primary cursor-pointer">{t("build.params")}</span>
                                        </TooltipTrigger>
                                        <TooltipContent side="right" className="bg-gray-50 border shadow-md p-4 text-gray-950 max-w-[520px]">
                                            <p className="flex gap-2 items-center"><Badge>{JSON.parse(api.extra)?.method || 'http'}</Badge><span className="text-xl">{api.name}</span></p>
                                            <p className="text-sm mt-2 text-gray-500">{api.desc}</p>
                                            {
                                                api.api_params.map(param => (
                                                    <div key={param.name}>
                                                        <p className="flex gap-2 items-center mt-4 mb-2">
                                                            <span className="text-base">{param.name}</span>
                                                            <span>{param.schema?.type}</span>
                                                            {param.required && <span className="text-red-500">必填</span>}
                                                        </p>
                                                        <p className="text-gray-500">{param.description}</p>
                                                    </div>
                                                ))
                                            }
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider>
                                :
                                {
                                    api.api_params.map(param => (
                                        <div>
                                            <span className=" rounded-xl bg-gray-200 dark:bg-background-login px-2 py-1 text-xs font-medium text-white">{param.name}</span>
                                            {/* <span>{param.schema.type}</span> */}
                                        </div>
                                    ))
                                }
                            </p>
                        }
                        {
                            select && (select.some(_ => _.id === api.id) ?
                                <Button size="sm" className="absolute right-4 bottom-2 h-6" disabled>{t("build.added")}</Button>
                                : <Button size="sm" className="absolute right-4 bottom-2 h-6" onClick={() => onSelect(api)}>{t("build.add")}</Button>)
                        }
                    </div>
                ))}
            </div>
        </AccordionContent>
    </AccordionItem >
}
