import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { getChatOnlineApi } from "@/controllers/API/assistant";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";
import { SkillIcon } from "@/components/bs-icons/skill";
import { AssistantIcon } from "@/components/bs-icons/assistant";
import { useTranslation } from "react-i18next";

export default function SkillChatSheet({ children, onSelect }) {
    const [open, setOpen] = useState(false)

    const { t } = useTranslation()

    const navigate = useNavigate()

    const [keyword, setKeyword] = useState(' ')
    const allDataRef = useRef([])

    useEffect(() => {
        open && getChatOnlineApi().then(res => {
            allDataRef.current = res
            setKeyword('')
        })
        // setKeyword(' ')
    }, [open])

    const options = useMemo(() => {
        return allDataRef.current.filter(el => el.name.toLowerCase().includes(keyword.toLowerCase()))
    }, [keyword])

    return <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="sm:min-w-[966px] bg-gray-100">
            <div className="flex h-full" onClick={e => e.stopPropagation()}>
                <div className="w-fit p-6">
                    <SheetTitle>{t('chat.dialogueSelection')}</SheetTitle>
                    <SheetDescription>{t('chat.chooseSkillOrAssistant')}</SheetDescription>
                    <SearchInput value={keyword} placeholder={t('chat.search')} className="my-6" onChange={(e) => setKeyword(e.target.value)} />
                </div>
                <div className="flex-1 min-w-[696px] bg-[#fff] p-5 pt-12 h-full flex flex-wrap gap-1.5 overflow-y-auto scrollbar-hide content-start">
                    {
                        options.length ? options.map((flow, i) => (
                            <CardComponent key={i}
                                id={i + 1}
                                data={flow}
                                title={flow.name}
                                description={flow.desc}
                                type="sheet"
                                icon={flow.flow_type === 'flow' ? SkillIcon : AssistantIcon}
                                footer={
                                    <Badge className={`absolute right-0 bottom-0 rounded-none rounded-br-md ${flow.flow_type === 'flow' && 'bg-gray-950'}`}>
                                        {flow.flow_type === 'flow' ? '技能' : '助手'}
                                    </Badge>
                                }
                                onClick={() => { onSelect(flow); setOpen(false) }}
                            />
                        )) : <div className="flex flex-col items-center justify-center pt-40 w-full">
                            <p className="text-sm text-muted-foreground mb-3">空空如也</p>
                            <Button className="w-[200px]" onClick={() => navigate('/build/assist')}>去上线技能&助手</Button>
                        </div>
                    }
                </div>
            </div>
        </SheetContent>
    </Sheet>
};
