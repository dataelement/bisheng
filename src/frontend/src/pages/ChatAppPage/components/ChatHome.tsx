import CardComponent from "@/components/bs-comp/cardComponent";
import LoadMore from "@/components/bs-comp/loadMore";
import { AssistantIcon, FlowIcon, SettingIcon, SkillIcon } from "@/components/bs-icons";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { userContext } from "@/contexts/userContext";
import { getChatOnlineApi } from "@/controllers/API/assistant";
import { getHomeLabelApi } from "@/controllers/API/label";
import { useDebounce } from "@/util/hook";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import MarkLabel from "./MarkLabel";

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
    const [flag, setFlag] = useState(null) // 解决筛选之后再次发起请求覆盖筛选数据

    const loadData = (more = false) => {
        getChatOnlineApi(pageRef.current, searchRef.current, -1).then((res: any) => {
            setFlag(true)
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

    const [chooseId, setChooseId] = useState() // 筛选项样式变化
    const handleTagSearch = (id) => {
        setChooseId(id)
        setFlag(false)
        pageRef.current = 1
        getChatOnlineApi(pageRef.current, '', id).then((res: any) => {
            setOptions(res)
        })
    }

    const handleLoadMore = async () => {
        pageRef.current++
        await debounceLoad(true)
    }

    // const [cardBoxWidth, cardboxRef] = useAutoWidth()
    const typeNames = {
        'flow': t('build.skill'),
        'assistant': t('build.assistant'),
        'workflow': '工作流'
    }
    {/* @ts-ignore */ }
    return <div className="h-full overflow-hidden bs-chat-bg" style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/points.png)` }}>
        <div className="flex justify-center place-items-center gap-20">
            {/* @ts-ignore */}
            <img className="w-[138px]" src={__APP_ENV__.BASE_URL + '/application-start-logo.png'} alt="" />
            <p className="text-2xl leading-[50px] dark:text-[#D4D4D4]">
                {t('chat.chooseOne')}<b className=" dark:text-[#D4D4D4] font-semibold">{t('chat.dialogue')}</b><br />{t('chat.start')}<b className=" dark:text-[#D4D4D4] font-semibold">{t('chat.wenqingruijian')}</b>
            </p>
        </div>
        <div className="flex justify-center">
            <SearchInput onChange={handleSearch}
                placeholder={t('chat.searchAssistantOrSkill')}
                className="w-[600px] min-w-[300px] mt-[10px]" />
        </div>
        <div className="mt-[20px] px-12">
            <div className="flex flex-wrap">
                <Button variant={chooseId ? "outline" : "default"} className="mb-2 mr-4 h-7" size="sm"
                    onClick={() => { setChooseId(null); loadData(false) }}>{t('all')}</Button>
                {
                    labels.map((l, index) => index <= 11 && <Button
                        size="sm"
                        onClick={() => handleTagSearch(l.value)}
                        className="mr-3 mb-2 h-7" variant={l.value === chooseId ? "default" : "outline"}>{l.label}
                    </Button>)
                }
                {/* @ts-ignore */}
                {user.role === 'admin' && <SettingIcon onClick={() => setOpen(true)} className="h-[30px] w-[30px] cursor-pointer" />}
            </div>
        </div>
        <div className="relative overflow-y-auto h-[calc(100vh-308px)]">
            <div className="flex flex-wrap gap-2 px-12 scrollbar-hide pt-4 pb-20" >
                {
                    options.length ? options.map((flow, i) => (
                        <CardComponent key={i}
                            id={i + 1}
                            data={flow}
                            logo={flow.logo}
                            title={flow.name}
                            description={flow.desc}
                            type="sheet"
                            icon={flow.flow_type === 'flow' ? SkillIcon : flow.flow_type === 'assistant' ? AssistantIcon : FlowIcon}
                            footer={
                                <Badge className={`absolute right-0 bottom-0 rounded-none rounded-br-md  ${flow.flow_type === 'flow' && 'bg-gray-950'} ${flow.flow_type === 'assistant' && 'bg-blue-600'}`}>
                                    {typeNames[flow.flow_type]}
                                </Badge>
                            }
                            onClick={() => { onSelect(flow) }}
                        />
                    )) : <div className="absolute top-1/2 left-1/2 transform text-center -translate-x-1/2 -translate-y-1/2">
                        <p className="text-sm text-muted-foreground mb-3">{t('build.empty')}</p>
                        <Button className="w-[200px]" onClick={() => navigate('/build/assist')}>{t('build.onlineSA')}</Button>
                    </div>
                }
                {flag && <LoadMore onScrollLoad={handleLoadMore} />}
            </div>
        </div>
        <MarkLabel open={open} home={labels} onClose={handleClose}></MarkLabel>
    </div>
}


const useAutoWidth = () => {
    const [width, setWidth] = useState(0);
    const cardboxRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const resize = () => {
            // console.log('cardboxRef.current.width :>> ', cardboxRef.current.offsetWidth);
            setWidth(Math.floor(cardboxRef.current.offsetWidth / 323) * 323)
        }
        if (cardboxRef.current) {
            window.addEventListener('resize', resize)
            resize()
        }

        return () => {
            window.removeEventListener('resize', resize)
        }
    }, []);
    return [width, cardboxRef];

}