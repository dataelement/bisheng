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
            <div className="px-6 pb-4 space-y-2">
                {sortData.map(api => {
                    const toolDisplayName = type ? api.name : t(`tools.${api.tool_key}.name`, { defaultValue: api.name });
                    const toolDesc = type ? api.name : t(`tools.${api.tool_key}.desc`, { defaultValue: api.description || '' });
                    const pricingItem = pricingMap?.[String(api.id)];
                    const isFree = !pricingItem || pricingItem.price_micro === 0;

                    return (
                        <div
                            key={api.name}
                            className="flex flex-col gap-3 rounded-lg bg-muted/40 px-4 py-3 transition-colors hover:bg-muted/60 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
                        >
                            <div className="min-w-0 flex-1">
                                <h1 className="text-sm font-medium leading-snug text-foreground">{toolDisplayName}</h1>
                                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{toolDesc}</p>
                                {api.api_params?.length > 0 && (
                                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                                        <Tooltip side="right" content={<>
                                            {/* todo  JSON.parse(api.extra) move to api ctr */}
                                            <p className="flex gap-2 items-center"><Tag size="small">{JSON.parse(api.extra)?.method || 'http'}</Tag><span className="text-xl">{toolDisplayName}</span></p>
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
                                        </>}>
                                            <span className="text-primary cursor-pointer inline-flex items-center gap-0.5">
                                                {t("build.params", { ns: 'bs' })}
                                                <Outlined.Question className="size-3" />
                                            </span>
                                        </Tooltip>
                                        <span>:</span>
                                        {api.api_params.map(param => (
                                            <span
                                                key={param.name}
                                                className="rounded-md bg-background/80 border border-border/50 px-2 py-0.5 text-xs font-medium text-foreground/80"
                                            >
                                                {param.name}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                            {(showPricing || select) && (
                                <div className="flex shrink-0 flex-wrap items-center gap-3 self-end sm:self-center">
                                    {showPricing && (
                                        <div className="flex items-center gap-3">
                                            <span className={`text-xs whitespace-nowrap ${isFree ? 'text-muted-foreground' : 'font-medium text-foreground'}`}>
                                                {isFree
                                                    ? t('pricing.free')
                                                    : pricingItem.pricing_mode === 'MONEY'
                                                        ? t('pricing.summaryMoney', {
                                                            symbol: currencySymbol(pricingItem.currency),
                                                            price: pricingItem.price,
                                                            count: pricingItem.call_count,
                                                            credits: pricingItem.estimated_credits,
                                                        })
                                                        : pricingItem.call_count > 1
                                                            ? t('pricing.summaryCredits', {
                                                                price: pricingItem.price,
                                                                count: pricingItem.call_count,
                                                                credits: pricingItem.estimated_credits,
                                                            })
                                                            : t('pricing.summaryCreditsSingle', {
                                                                price: pricingItem.price,
                                                                count: pricingItem.call_count,
                                                            })}
                                            </span>
                                            {onSetPrice && (
                                                <Button
                                                    variant="link"
                                                    size="small"
                                                    className="h-auto px-0 text-xs font-medium shrink-0"
                                                    onClick={() =>
                                                        onSetPrice({
                                                            id: api.id,
                                                            name: toolDisplayName,
                                                            tool_key: api.tool_key,
                                                        })
                                                    }
                                                >
                                                    {t('pricing.setPrice')}
                                                </Button>
                                            )}
                                        </div>
                                    )}
                                    {select && (
                                        select.some(_ => _.id === api.id)
                                            ? <Button size="small" disabled>{t("build.added", { ns: 'bs' })}</Button>
                                            : <Button size="small" onClick={() => onSelect(api)}>{t("build.add", { ns: 'bs' })}</Button>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </AccordionContent>
    </AccordionItem >
}
