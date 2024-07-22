import { SettingIcon } from "@/components/bs-icons"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import { useTranslation } from "react-i18next"
import { userContext } from "@/contexts/userContext";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { CaretDownIcon } from "@radix-ui/react-icons";
import { SelectHover, SelectHoverItem } from "@/components/bs-ui/select/hover";
import { getChatOnlineApi } from "@/controllers/API/assistant";
import CardComponent from "@/components/bs-comp/cardComponent";
import { SkillIcon, AssistantIcon } from "@/components/bs-icons";
import { Badge } from "@/components/bs-ui/badge";
import { useNavigate } from "react-router-dom";
import MarkLabel from "./MarkLabel";
import { getHomeLabelApi } from "@/controllers/API/label";
import LoadMore from "@/components/bs-comp/loadMore";
import { useDebounce } from "@/util/hook";

export default function HomePage({ onSelect }) {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const chatListRef = useRef([])
    const navigate = useNavigate()

    const [labels, setLabels] = useState([])
    const [open, setOpen] = useState(false)
    const pageRef = useRef(1)
    const [options, setOptions] = useState([])
    const searchRef = useRef('')

    const loadData = (more = false) => {
        getChatOnlineApi(pageRef.current, searchRef.current, -1).then((res: any) => {
            chatListRef.current = res
            setOptions(more ? [...options, ...res] : res)
        })
    }
    useEffect(() => {
        debounceLoad()
        getHomeLabelApi().then((res: any) => {
            setLabels(res.map(d => ({ label: d.name, value: d.id, selected: true })))
        })
    }, [])

    const debounceLoad = useDebounce(loadData, 600, false)

    const handleSearch = (e) => {
        pageRef.current = 1
        searchRef.current = e.target.value
        debounceLoad()
    }

    const handleClose = async (bool) => {
        const newHome = await getHomeLabelApi()
        // @ts-ignore
        setLabels(newHome.map(d => ({ label: d.name, value: d.id, selected: true })))
        setOpen(bool)
    }

    const handleTagSearch = (id) => {
        pageRef.current = 1
        getChatOnlineApi(pageRef.current, '', id).then((res:any) => {
            setOptions(res)
        })
    }

    const handleLoadMore = () => {
        pageRef.current++
        debounceLoad(true)
    }

    {/* @ts-ignore */ }
    return <div className="h-full overflow-hidden bs-chat-bg px-[40px]" style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/points.png)` }}>
        <div className="flex flex-col place-items-center">
            <div className="flex flex-row place-items-center">
                {/* @ts-ignore */}
                <img className="w-[150px] h-[136.5px] mx-auto" src={__APP_ENV__.BASE_URL + '/application-start-logo.png'} alt="" />
                <p className="text-2xl ml-16 whitespace-normal leading-[50px] dark:text-[#D4D4D4] mx-auto font-light">
                    {t('chat.chooseOne')}<b className=" dark:text-[#D4D4D4] font-semibold">{t('chat.dialogue')}</b><br />{t('chat.start')}<b className=" dark:text-[#D4D4D4] font-semibold">{t('chat.wenqingruijian')}</b>
                </p>
            </div>
            <SearchInput onChange={handleSearch} placeholder="搜索助手或者技能" className="w-[600px] mt-[20px]" />
        </div>
        <div className="mt-[20px] flex items-center">
            <div>
                <Button>全部</Button>
                {
                    labels.map((l, index) => index <= 11 && <Button
                        onClick={() => handleTagSearch(l.value)}
                        className="ml-5" variant="outline">{l.label}</Button>)
                }
            </div>
            {labels.length > 10 && <div className="ml-5">
                <SelectHover triagger={
                    <CaretDownIcon className="h-[35px] w-[35px] text-gray-500" />
                }>
                    <SelectHoverItem><span>折叠标签1</span></SelectHoverItem>
                    <SelectHoverItem><span>折叠标签1</span></SelectHoverItem>
                </SelectHover>
            </div>}
            {/* @ts-ignore */}
            {user.role === 'admin' && <SettingIcon onClick={() => setOpen(true)} className="h-[30px] w-[30px] cursor-pointer ml-5" />}
        </div>
        <div className="flex-1 min-w-[696px] mt-8 pb-24 h-[calc(100vh-348px)] flex flex-wrap gap-1.5 overflow-y-auto scrollbar-hide content-start">
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
                        onClick={() => { onSelect(flow) }}
                    />
                )) : <div className="flex flex-col items-center justify-center pt-40 w-full">
                    <p className="text-sm text-muted-foreground mb-3">{t('build.empty')}</p>
                    <Button className="w-[200px]" onClick={() => navigate('/build/assist')}>{t('build.onlineSA')}</Button>
                </div>
            }
            <LoadMore onScrollLoad={handleLoadMore} />
        </div>
        <MarkLabel open={open} home={labels} onClose={handleClose}></MarkLabel>
    </div>
}