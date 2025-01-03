import { readTempsDatabase } from "@/controllers/API";
import { AppType } from "@/types/app";
import { Bot } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";

/** 应用模板选择 */
export default function AppTempSheet({ children, onCustomCreate, onSelect }) {
    const [open, setOpen] = useState(false)
    const [type, setType] = useState<AppType>(AppType.FLOW)
    const { t } = useTranslation('flow')
    const createDesc = useMemo(() => {
        const descs = {
            [AppType.ASSISTANT]: {
                title: t('customAssistant'),
                desc: <>
                    <p>{t('createAppWithNoCode')}</p>
                    <p>{t('assistantCanUseSkillsAndTools')}</p>
                </>
            },
            [AppType.FLOW]: {
                title: t('customWorkflow'),
                desc: t('simpleNodeOrchestration')
            },
            [AppType.SKILL]: {
                title: t('customSkill'),
                desc: t('richComponentsForBuildingApps')
            }
        }
        return descs[type]
    }, [type])

    const [keyword, setKeyword] = useState(' ')
    const allDataRef = useRef([])

    useEffect(() => {
        setKeyword(' ')
        readTempsDatabase(type).then(res => {
            allDataRef.current = res
            setKeyword('')
        })
    }, [type])

    const options = useMemo(() => {
        return allDataRef.current.filter(el => el.name.toLowerCase().includes(keyword.toLowerCase()))
    }, [keyword])

    return <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="sm:min-w-[966px] ">
            <div className="flex h-full" onClick={e => e.stopPropagation()}>
                <div className="w-fit p-6">
                    <SheetTitle>{t('appTemplate')}</SheetTitle>
                    <SheetDescription>{t('chooseTemplateOrCreateBlank')}</SheetDescription>
                    <SearchInput value={keyword} placeholder={t('search')} className="my-6" onChange={(e) => setKeyword(e.target.value)} />
                    {/* type */}
                    <div className="mt-4">
                        <div
                            className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mb-2 ${type === AppType.FLOW && 'bg-muted-foreground/10'}`}
                            onClick={() => setType(AppType.FLOW)}
                        >
                            {/* <Bot /> */}
                            <span>{t('workflow')}</span>
                        </div>
                        <div
                            className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mb-2 ${type === AppType.ASSISTANT && 'bg-muted-foreground/10'}`}
                            onClick={() => setType(AppType.ASSISTANT)}
                        >
                            {/* <Bot /> */}
                            <span>{t('assistant')}</span>
                        </div>
                        <div
                            className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mb-2 ${type === AppType.SKILL && 'bg-muted-foreground/10'}`}
                            onClick={() => setType(AppType.SKILL)}
                        >
                            {/* <Bot /> */}
                            <span>{t('skill')}</span>
                        </div>
                    </div>
                </div>
                <div className="flex-1 min-w-[696px] bg-[#fff] dark:bg-[#030712] p-5 pt-12 h-full flex flex-wrap gap-1.5 overflow-y-auto scrollbar-hide content-start">
                    <CardComponent
                        id={0}
                        type="sheet"
                        data={null}
                        title={createDesc.title}
                        description={createDesc.desc}
                        onClick={() => { onCustomCreate(type); setOpen(false) }}
                    // onClick={() => navigate('/build/skill')}
                    ></CardComponent>
                    {
                        options.map((flow, i) => (
                            <CardComponent key={i}
                                id={i + 1}
                                data={flow}
                                logo={flow.logo}
                                title={flow.name}
                                description={flow.description}
                                type="sheet"
                                footer={null}
                                onClick={() => { onSelect(type, flow.id); setOpen(false) }}
                            />
                        ))
                    }
                </div>
            </div>
        </SheetContent>
    </Sheet>
};
