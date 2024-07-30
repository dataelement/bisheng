import { readTempsDatabase } from "@/controllers/API";
import { useEffect, useMemo, useRef, useState } from "react";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

export default function SkillTempSheet({ children, onSelect }) {
    const [open, setOpen] = useState(false)

    const navigate = useNavigate()
    const { t } = useTranslation()

    const [keyword, setKeyword] = useState(' ')
    const allDataRef = useRef([])

    useEffect(() => {
        readTempsDatabase().then(res => {
            allDataRef.current = res
            setKeyword('')
        })
    }, [])

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
                    <SheetTitle>{t('skills.skillTemplate')}</SheetTitle>
                    <SheetDescription>{t('skills.skillTemplateChoose')}</SheetDescription>
                    <SearchInput value={keyword} placeholder={t('build.search')} className="my-6" onChange={(e) => setKeyword(e.target.value)} />
                </div>
                <div className="flex-1 min-w-[696px] bg-[#fff] dark:bg-[#030712] p-5 pt-12 h-full flex flex-wrap gap-1.5 overflow-y-auto scrollbar-hide content-start">
                    <CardComponent
                        id={0}
                        type="sheet"
                        data={null}
                        title={t('skills.customSkills')}
                        description=''
                        onClick={() => navigate('/build/skill')}
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
                                onClick={() => { onSelect(flow.id); setOpen(false) }}
                            />
                        ))
                    }
                </div>
            </div>
        </SheetContent>
    </Sheet>
};
