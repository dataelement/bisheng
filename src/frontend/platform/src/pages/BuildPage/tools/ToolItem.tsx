// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { Outlined } from "bisheng-icons";


import {
AccordionContent,
AccordionItem,
AccordionTrigger,
} from "@/components/bs-ui/accordion";

import { Tag,Tooltip } from "@bisheng/ui";
import { Shield } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export default function ToolItem({
    type,
    select,
    data,
    onEdit = (id) => { },
    onSelect,
    onSetClick = null,
    onPermission = null,
    onHoverPermissions = null,
    permissionBadge = null,
}) {
    const { t } = useTranslation('tool');
    const sortData = useMemo(() => {
        const { children, is_preset } = data;
        if (children) {
            return is_preset === 2 ? children.sort((a, b) => a.id - b.id) : children;
        }
        return [];
    }, [data.children]);

    return <AccordionItem key={data.id} value={data.id} className="data-[state=open]:border-2 data-[state=open]:border-primary/20 data-[state=open]:rounded-md">
        <AccordionTrigger className="min-w-0">
            <div
                className="group flex gap-2 text-start relative pr-4 min-w-0"
                onMouseEnter={() => onHoverPermissions?.(data)}
            >
                <TitleIconBg className="w-8 h-8 min-w-8" id={data.id} ><Outlined.Hammer size={20} className="text-white" /></TitleIconBg>
                <div className="flex-1 min-w-0">
                    <div className="w-full text-sm font-medium leading-none flex items-center gap-2 min-w-0">
                        <span className="truncate">
                            {type ? data.name : t(`categories.${data.name}.name`)}
                        </span>
                        {permissionBadge}
                        {
                            onPermission && <div
                                className="group-hover:opacity-100 opacity-0 hover:bg-[#EAEDF3] dark:hover:bg-[#34353A] rounded cursor-pointer p-1"
                                onClick={(e) => { e.stopPropagation(); onPermission(data) }}
                            ><Shield className="w-4 h-4" /></div>
                        }
                        {
                            ['edit', 'mcp'].includes(type) && data.write && <div
                                className="group-hover:opacity-100 opacity-0 hover:bg-[#EAEDF3] rounded cursor-pointer"
                                onClick={(e) => onEdit(data.id)}
                            ><Outlined.Setting size={16} className="shrink-0" aria-label={t("edit", { ns: "bs" })} /></div>
                        }
                        {
                            onSetClick && data.write && !['mcp'].includes(type) && <div
                                className="group-hover:opacity-100 opacity-0 hover:bg-[#EAEDF3] rounded cursor-pointer"
                                onClick={onSetClick}
                            ><Outlined.Setting size={16} className="shrink-0" aria-label={t("edit", { ns: "bs" })} /></div>
                        }
                    </div>
                    <p className="text-sm text-muted-foreground mt-2">{type ? data.description : t(`categories.${data.name}.desc`)}</p>
                </div>
            </div>
        </AccordionTrigger>
        <AccordionContent className="">
            <div className="px-6 mb-4">
                {sortData.map(api => (
                    <div key={api.name} className="relative p-4 rounded-sm  border-t">
                        <h1 className="text-sm font-medium leading-none">{type ? api.name : t(`tools.${api.tool_key}.name`)}</h1>
                        <p className="text-sm text-muted-foreground mt-2">{type ? api.name : t(`tools.${api.tool_key}.desc`)}</p>
                        {
                            api.api_params?.length > 0 && <p className="text-sm text-muted-foreground mt-2 flex gap-2">
                                <Tooltip side="right" content={<>
                                            {/* todo  JSON.parse(api.extra) move to api ctr */}
                                            <p className="flex gap-2 items-center"><Tag size="small">{JSON.parse(api.extra)?.method || 'http'}</Tag><span className="text-xl">{type ? api.name : t(`tools.${api.tool_key}.name`)}</span></p>
                                            <p className="text-sm mt-2 ">{type ? api.name : t(`tools.${api.tool_key}.desc`)}</p>
                                            {
                                                api.api_params.map(param => (
                                                    <div key={param.name}>
                                                        <p className="flex gap-2 items-center mt-4 mb-2">
                                                            <span className="text-base">{param.name}</span>
                                                            <span>{param.schema?.type}</span>
                                                            {param.required && <span className="text-red-500">{t('report.requiredLabel', { ns: 'bs' })}</span>}
                                                        </p>
                                                        <p className="">{type ? param.name : t(`tools.${api.tool_key}.params.${param.name}`)}</p>
                                                    </div>
                                                ))
                                            }
                                         </>}><span className="text-primary cursor-pointer flex items-center">{t("build.params", { ns: 'bs' })}<Outlined.Question className="size-3" /></span></Tooltip>
                                :
                                {
                                    api.api_params.map(param => (
                                        <div>
                                            <span className=" rounded-xl bg-gray-200 dark:bg-background-login px-2 py-1 text-xs font-medium">{param.name}</span>
                                            {/* <span>{param.schema.type}</span> */}
                                        </div>
                                    ))
                                }
                            </p>
                        }
                        {
                            select && (select.some(_ => _.id === api.id) ?
                                <Button size="small" className="absolute right-4 bottom-2 h-6" disabled>{t("build.added", { ns: 'bs' })}</Button>
                                : <Button size="small" className="absolute right-4 bottom-2 h-6" onClick={() => onSelect(api)}>{t("build.add", { ns: 'bs' })}</Button>)
                        }
                    </div>
                ))}
            </div>
        </AccordionContent>
    </AccordionItem >
}
