import CardComponent from "@/components/bs-comp/cardComponent";
import LoadMore from "@/components/bs-comp/loadMore";
import { AssistantIcon, SettingIcon, SkillIcon } from "@/components/bs-icons";
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
        getChatOnlineApi(pageRef.current, '', id).then((res:any) => {
            setOptions(res)
        })
    }

    const handleLoadMore = async () => {
        pageRef.current++
        await debounceLoad(true)
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
            <SearchInput onChange={handleSearch} placeholder="搜索助手或者技能" className="w-[600px] min-w-[300px] mt-[20px]" />
        </div>
        <div className="mt-[20px] w-full">
            <div className="flex items-center justify-center flex-wrap">
                <Button variant={chooseId ? "outline" : "default"} className="mb-2 mr-5"
                onClick={() => { setFlag(true); setChooseId(null); loadData(true) }}>全部</Button>
                {
                    labels.map((l, index) => index <= 11 && <Button
                        onClick={() => handleTagSearch(l.value)}
                        className="mr-5 mb-2" variant={l.value === chooseId ? "default" : "outline"}>{l.label}
                        </Button>)
                }
                {/* @ts-ignore */}
                {user.role === 'admin' && <SettingIcon onClick={() => setOpen(true)} className="h-[30px] w-[30px] cursor-pointer" />}
            </div>
        </div>
        <div className="flex-1 justify-evenly min-w-[696px] mt-6 pb-24 h-[calc(100vh-348px)] flex flex-wrap gap-3 overflow-y-auto scrollbar-hide content-start">
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
            {flag && <LoadMore onScrollLoad={handleLoadMore} />}
        </div>
        <MarkLabel open={open} home={labels} onClose={handleClose}></MarkLabel>
    </div>
}