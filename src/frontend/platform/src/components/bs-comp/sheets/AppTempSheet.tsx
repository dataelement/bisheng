// @ts-strict-ignore
import { FlowIcon, HelperIcon } from "@/components/bs-icons/app";
import { readTempsDatabase } from "@/controllers/API";
import { AppType, AppTypeToNum } from "@/types/app";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";
import AppAvator from "../cardComponent/avatar";

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
            }
        }
        return descs[type]
    }, [type, t])

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
            <div className="app-sheet flex h-full" onClick={e => e.stopPropagation()}>
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
                            <FlowIcon />
                            <span>{t('workflow')}</span>
                        </div>
                        <div
                            className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mb-2 ${type === AppType.ASSISTANT && 'bg-muted-foreground/10'}`}
                            onClick={() => setType(AppType.ASSISTANT)}
                        >
                            <HelperIcon />
                            <span>{t('assistant')}</span>
                        </div>
                    </div>
                    {/* Hosted app: not a template category — a shortcut to the
                        "write your own code and deploy it" tutorial. Opens in a new
                        tab so the drawer / builder stays put. */}
                    <div className="mt-4 pt-4 border-t border-border w-[210px]">
                        <div
                            className="group flex flex-col gap-1.5 px-4 py-3 rounded-lg cursor-pointer border border-dashed border-border transition-all hover:border-primary/60 hover:bg-primary/5"
                            onClick={() => window.open('/tutorial/hosted-app.html', '_blank', 'noopener')}
                        >
                            <div className="flex items-center gap-2 text-sm font-medium">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary shrink-0">
                                    <rect x="3" y="4" width="18" height="16" rx="2" />
                                    <polyline points="8 9 11 12 8 15" />
                                    <line x1="14" y1="15" x2="16" y2="15" />
                                </svg>
                                <span>{t('hostedApp')}</span>
                            </div>
                            <span className="text-xs text-muted-foreground leading-snug">{t('hostedAppDesc')}</span>
                            <span className="text-xs font-medium text-primary group-hover:underline">{t('viewTutorial')} →</span>
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
                    ></CardComponent>
                    {
                        options.map((flow, i) => (
                            <CardComponent key={i}
                                id={i + 1}
                                data={flow}
                                logo={<AppAvator id={flow.name} flowType={AppTypeToNum[type]} url={flow.logo} />}
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
