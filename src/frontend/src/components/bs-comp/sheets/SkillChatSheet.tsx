import { AssistantIcon, SkillIcon } from "@/components/bs-icons";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { getChatOnlineApi } from "@/controllers/API/assistant";
import { useDebounce } from "@/util/hook";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";
import LoadMore from "../loadMore";

export default function SkillChatSheet({ children, onSelect }) {
    const [open, setOpen] = useState(false)
    const { t } = useTranslation()
    const navigate = useNavigate()

    const pageRef = useRef(1)
    const searchRef = useRef('')
    const [options, setOptions] = useState<any>([])

    const loadData = (more = false) => {
        open && getChatOnlineApi(pageRef.current, searchRef.current).then(res => {
            setOptions(opts => more ? [...opts, ...res] : res)
        })
    }
    const debounceLoad = useDebounce(loadData, 600, false)

    useEffect(() => {
        pageRef.current = 1
        searchRef.current = ''
        loadData()
    }, [open])

    const handleSearch = (e) => {
        pageRef.current = 1
        searchRef.current = e.target.value
        debounceLoad()
    }

    const handleLoadMore = () => {
        pageRef.current++
        loadData(true)
    }

    return <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="sm:min-w-[966px]">
            <div className="flex h-full" onClick={e => e.stopPropagation()}>
                <div className="w-fit p-6">
                    <SheetTitle>{t('chat.dialogueSelection')}</SheetTitle>
                    <SheetDescription>{t('chat.chooseSkillOrAssistant')}</SheetDescription>
                    <SearchInput placeholder={t('chat.search')} className="my-6" onChange={handleSearch} />
                </div>
                <div className="flex-1 min-w-[696px] bg-[#fff] dark:bg-[#030712] p-5 pt-12 h-full flex flex-wrap gap-1.5 overflow-y-auto scrollbar-hide content-start">
                    {
                        options.length ? options.map((flow, i) => (
                            <CardComponent key={i}
                                id={i + 1}
                                data={flow}
                                logo={flow.logo}
                                title={flow.name}
                                description={flow.desc}
                                type="sheet"
                                icon={flow.flow_type === 'flow' ? SkillIcon : AssistantIcon}
                                footer={
                                    <Badge className={`absolute right-0 bottom-0 rounded-none rounded-br-md ${flow.flow_type === 'flow' && 'bg-gray-950'}`}>
                                        {flow.flow_type === 'flow' ? t('build.skill') : t('build.assistant')}
                                    </Badge>
                                }
                                onClick={() => { onSelect(flow); setOpen(false) }}
                            />
                        )) : <div className="flex flex-col items-center justify-center pt-40 w-full">
                            <p className="text-sm text-muted-foreground mb-3">{t('build.empty')}</p>
                            <Button className="w-[200px]" onClick={() => navigate('/build/assist')}>{t('build.onlineSA')}</Button>
                        </div>
                    }
                    <LoadMore onScrollLoad={handleLoadMore} />
                </div>
            </div>
        </SheetContent>
    </Sheet>
};
