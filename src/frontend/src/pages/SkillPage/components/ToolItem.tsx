import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { ToolIcon } from "@/components/bs-icons/tool";
import {
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { useTranslation } from "react-i18next";

export default function ToolItem({
    type,
    select,
    data,
    onEdit = (id) => { },
    onSelect,
}) {
    const { t } = useTranslation();


    return <AccordionItem key={data.id} value={data.id} className="data-[state=open]:border-2 data-[state=open]:border-primary/20 data-[state=open]:rounded-md">
        <AccordionTrigger>
            <div className="group w-full flex gap-2 text-start relative pr-4">
                <TitleIconBg className="w-8 h-8 min-w-8" id={data.id} ><ToolIcon /></TitleIconBg>
                <div className="flex-1 min-w-0">
                    <p className="w-full text-sm font-medium leading-none flex justify-between">{data.name}
                        {type === 'edit' && <Button size="sm" className="ml-4 h-6 group-hover:visible invisible" onClick={(e) => onEdit(data.id)}>{t("edit")}</Button>}
                    </p>
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
                        <p className="text-sm text-muted-foreground mt-2 flex gap-2">
                            <span>{t("build.params")}</span>:
                            :
                            {
                                api.api_params.map(param => (
                                    <div>
                                        <span className=" rounded-xl bg-gray-200 px-2 py-1 text-xs font-medium text-white">{param.name}</span>
                                        {/* <span>{param.schema.type}</span> */}
                                    </div>
                                ))
                            }
                        </p>
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
