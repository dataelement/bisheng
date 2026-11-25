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
import type { ToolPricingItem } from "@/controllers/API/toolPricing";
import { Shield } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { currencySymbol } from "./ToolPriceDialog";

interface ToolApiParam {
    name: string;
    required?: boolean;
    schema?: { type?: string };
}

interface ToolChildItem {
    id: number;
    name: string;
    tool_key?: string;
    description?: string;
    desc?: string;
    extra?: string;
    api_params?: ToolApiParam[];
}

interface ToolGroupData {
    id: number | string;
    name: string;
    description?: string;
    is_preset?: number;
    write?: boolean;
    children?: ToolChildItem[];
}

interface ToolItemProps {
    type?: string;
    select?: Array<{ id: number | string }> | null;
    data: ToolGroupData;
    onEdit?: (id: number | string) => void;
    onSelect?: (tool: ToolChildItem) => void;
    onSetClick?: (() => void) | null;
    onPermission?: ((tool: ToolGroupData) => void) | null;
    onHoverPermissions?: ((tool: ToolGroupData) => void) | null;
    permissionBadge?: React.ReactNode;
    showPricing?: boolean;
    pricingMap?: Record<string, ToolPricingItem> | null;
    onSetPrice?: ((tool: { id: number; name: string; tool_key?: string }) => void) | null;
}

export default function ToolItem({
    type,
    select,
    data,
    onEdit = () => { },
    onSelect,
    onSetClick = null,
    onPermission = null,
    onHoverPermissions = null,
    permissionBadge = null,
    showPricing = false,
    pricingMap = null,
    onSetPrice = null,
}: ToolItemProps) {
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
                            {type ? data.name : t(`categories.${data.name}.name`, { defaultValue: data.name })}
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
                    <p className="text-sm text-muted-foreground mt-2">{type ? data.description : t(`categories.${data.name}.desc`, { defaultValue: data.description || '' })}</p>
                </div>
            </div>
        </AccordionTrigger>
        <AccordionContent className="">
            <div className="px-6 mb-4">
                {sortData.map(api => (
                    <div key={api.name} className="relative p-4 rounded-sm  border-t">
                        <h1 className="text-sm font-medium leading-none">{type ? api.name : t(`tools.${api.tool_key}.name`, { defaultValue: api.name })}</h1>
                        <p className="text-sm text-muted-foreground mt-2">{type ? api.name : t(`tools.${api.tool_key}.desc`, { defaultValue: api.description || '' })}</p>
                        {
                            api.api_params?.length > 0 && <p className="text-sm text-muted-foreground mt-2 flex gap-2">
                                <Tooltip side="right" content={<>
                                            {/* todo  JSON.parse(api.extra) move to api ctr */}
                                            <p className="flex gap-2 items-center"><Tag size="small">{JSON.parse(api.extra)?.method || 'http'}</Tag><span className="text-xl">{type ? api.name : t(`tools.${api.tool_key}.name`, { defaultValue: api.name })}</span></p>
                                            <p className="text-sm mt-2 ">{type ? api.name : t(`tools.${api.tool_key}.desc`, { defaultValue: api.description || "" })}</p>
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
                            showPricing && (
                                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                                    {(() => {
                                        const item = pricingMap?.[String(api.id)];
                                        if (!item || item.price_micro === 0) {
                                            return <span>{t('pricing.free')}</span>;
                                        }
                                        if (item.pricing_mode === 'MONEY') {
                                            return (
                                                <span>
                                                    {t('pricing.summaryMoney', {
                                                        symbol: currencySymbol(item.currency),
                                                        price: item.price,
                                                        count: item.call_count,
                                                        credits: item.estimated_credits,
                                                    })}
                                                </span>
                                            );
                                        }
                                        return (
                                            <span>
                                                {item.call_count > 1
                                                    ? t('pricing.summaryCredits', {
                                                        price: item.price,
                                                        count: item.call_count,
                                                        credits: item.estimated_credits,
                                                    })
                                                    : t('pricing.summaryCreditsSingle', {
                                                        price: item.price,
                                                        count: item.call_count,
                                                    })}
                                            </span>
                                        );
                                    })()}
                                    {onSetPrice && (
                                        <Button
                                            variant="link"
                                            size="small"
                                            className="h-auto px-0 text-xs"
                                            onClick={() =>
                                                onSetPrice({
                                                    id: api.id,
                                                    name: type ? api.name : t(`tools.${api.tool_key}.name`, { defaultValue: api.name }),
                                                    tool_key: api.tool_key,
                                                })
                                            }
                                        >
                                            {t('pricing.setPrice')}
                                        </Button>
                                    )}
                                </div>
                            )
                        }
                        {
                            select && (select.some(_ => _.id === api.id) ?
                                <Button size="small" className="absolute right-4 bottom-2" disabled>{t("build.added", { ns: 'bs' })}</Button>
                                : <Button size="small" className="absolute right-4 bottom-2" onClick={() => onSelect(api)}>{t("build.add", { ns: 'bs' })}</Button>)
                        }
                    </div>
                ))}
            </div>
        </AccordionContent>
    </AccordionItem >
}
