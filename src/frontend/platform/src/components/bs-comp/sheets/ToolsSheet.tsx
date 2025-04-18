import { Accordion } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import ToolItem from "@/pages/BuildPage/tools/ToolItem";
import { Star, User } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export default function ToolsSheet({ select, onSelect, children }) {
    const { t } = useTranslation()
    const [type, setType] = useState('default') // default custom

    const [keyword, setKeyword] = useState('')
    const [allData, setAllData] = useState([])

    useEffect(() => {
        getAssistantToolsApi(type).then(res => {
            setAllData(res)
            setKeyword('')
        })
    }, [type])

    const options = useMemo(() => {
        return allData.filter((el) => {
            // 搜索范围：工具名称、工具描述、工具api名称、工具api描述
            const targetStr = `${el.name}-${el.description}-${el.children?.map((el) => el.name + el.desc).join("-") || ''}`
            return targetStr.toLowerCase().includes(keyword.toLowerCase());
        });
    }, [keyword, allData])

    return (
        <Sheet onOpenChange={open => !open && setKeyword('')}>
            <SheetTrigger asChild>
                {children}
            </SheetTrigger>
            <SheetContent className="w-[1000px] sm:max-w-[1000px]">
                <div className="flex h-full" onClick={e => e.stopPropagation()}>
                    <div className="w-fit p-6">
                        <SheetTitle>{t('build.addTool')}</SheetTitle>
                        <SearchInput placeholder={t('build.search')} className="mt-6" onChange={(e) => setKeyword(e.target.value)} />
                        <Button
                            className="mt-4 w-full"
                            onClick={() => window.open(__APP_ENV__.BASE_URL + "/build/tools")}
                        >
                            {t('create')}{t("tools.createCustomTool")}
                        </Button>
                        <div className="mt-4">
                            <div
                                className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 ${type === 'default' && 'bg-muted-foreground/10'}`}
                                onClick={() => setType('default')}
                            >
                                <User />
                                <span>{t('tools.builtinTools')}</span>
                            </div>
                            <div
                                className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mt-1 ${type === 'custom' && 'bg-muted-foreground/10'}`}
                                onClick={() => setType('custom')}
                            >
                                <Star />
                                <span>{t('tools.customTools')}</span>
                            </div>
                        </div>
                    </div>
                    <div className="flex-1 bg-background-main p-5 pt-12 h-full overflow-auto scrollbar-hide">
                        <Accordion type="single" collapsible className="w-full">
                            {
                                options.length ? options.map(el => (
                                    <ToolItem
                                        key={el.id}
                                        type={'add'}
                                        select={select}
                                        data={el}
                                        onSelect={onSelect}
                                    ></ToolItem>
                                )) : <div className="pt-40 text-center text-sm text-muted-foreground mt-2">
                                    {t('build.empty')}
                                </div>
                            }
                        </Accordion>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );

};
