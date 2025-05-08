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
    const navigate = useNavigate()

    // State for UI and data
    const [categoryTags, setCategoryTags] = useState([])
    const [isLabelModalOpen, setIsLabelModalOpen] = useState(false)
    const [chatOptions, setChatOptions] = useState([])
    const [selectedCategoryId, setSelectedCategoryId] = useState(null)
    const [hasMoreData, setHasMoreData] = useState(false)

    // Refs for pagination and search
    const currentPageRef = useRef(1)
    const searchQueryRef = useRef('')
    const chatDataRef = useRef([])

    // Constants
    const CHAT_TYPE_NAMES = {
        1: t('build.skill'),
        5: t('build.assistant'),
        10: t('build.workflow')
    }
    const BASE_IMAGE_URL = __APP_ENV__.BASE_URL

    // Data fetching functions
    const fetchChatData = async (categoryId, loadMore = false) => {
        const response = await getChatOnlineApi(
            currentPageRef.current,
            searchQueryRef.current,
            categoryId
        )

        setSelectedCategoryId(categoryId)
        setHasMoreData(true)
        chatDataRef.current = response
        setChatOptions(loadMore ? [...chatOptions, ...response] : response)
    }

    const fetchCategoryTags = async () => {
        const tags = await getHomeLabelApi()
        setCategoryTags(tags.map(tag => ({
            label: tag.name,
            value: tag.id,
            selected: true
        })))
    }

    // Initial data load
    useEffect(() => {
        debounceFetchChatData(null)
        fetchCategoryTags()
    }, [])

    const debounceFetchChatData = useDebounce(fetchChatData, 600, false)

    // Event handlers
    const handleSearch = (e) => {
        currentPageRef.current = 1
        searchQueryRef.current = e.target.value
        debounceFetchChatData(selectedCategoryId)
    }

    const handleCloseLabelModal = async (shouldClose) => {
        if (shouldClose) {
            await fetchCategoryTags()
            setIsLabelModalOpen(false)
        } else {
            setIsLabelModalOpen(shouldClose)
        }
    }

    const handleCategoryFilter = (categoryId) => {
        setSelectedCategoryId(categoryId)
        setHasMoreData(false)
        currentPageRef.current = 1
        fetchChatData(categoryId)
    }

    const handleLoadMore = async () => {
        currentPageRef.current++
        await debounceFetchChatData(selectedCategoryId, true)
    }

    const renderCategoryTags = () => (
        <>
            <Button
                variant={!selectedCategoryId ? "default" : "outline"}
                className="mb-2 mr-4 h-7"
                size="sm"
                onClick={() => {
                    setHasMoreData(false)
                    currentPageRef.current = 1
                    fetchChatData(null, false)
                }}
            >
                {t('all')}
            </Button>
            {categoryTags.slice(0, 12).map((tag) => (
                <Button
                    key={tag.value}
                    size="sm"
                    onClick={() => handleCategoryFilter(tag.value)}
                    className="mr-3 mb-2 h-7"
                    variant={tag.value === selectedCategoryId ? "default" : "outline"}
                >
                    {tag.label}
                </Button>
            ))}
        </>
    )

    const renderChatOptions = () => {
        if (!chatOptions.length && hasMoreData) {
            return (
                <div className="absolute top-1/2 left-1/2 transform text-center -translate-x-1/2 -translate-y-1/2">
                    <p className="text-sm text-muted-foreground mb-3">{t('build.empty')}</p>
                    <Button className="w-[200px]" onClick={() => navigate('/build/apps')}>
                        {t('build.onlineSA')}
                    </Button>
                </div>
            )
        }

        return chatOptions.map((chat, index) => (
            <CardComponent
                key={index}
                id={index + 1}
                data={chat}
                logo={chat.logo}
                title={chat.name}
                description={chat.description}
                type="sheet"
                icon={getChatTypeIcon(chat.flow_type)}
                footer={renderChatTypeBadge(chat.flow_type)}
                onClick={() => onSelect(chat)}
            />
        ))
    }

    const getChatTypeIcon = (type) => {
        return type === 'flow' ? SkillIcon :
            type === 'assistant' ? AssistantIcon : FlowIcon
    }

    const renderChatTypeBadge = (type) => (
        <Badge className={`absolute right-0 bottom-0 rounded-none rounded-br-md ${type === 1 ? 'bg-gray-950' :
            type === 5 ? 'bg-[#fdb136]' : ''
            }`}>
            {CHAT_TYPE_NAMES[type]}
        </Badge>
    )

    return (
        <div className="h-full overflow-hidden bs-chat-bg"
            style={{ backgroundImage: `url(${BASE_IMAGE_URL}/points.png)` }}>

            <HeaderSection BASE_IMAGE_URL={BASE_IMAGE_URL} t={t} />

            <div className="flex justify-center">
                <SearchInput
                    onChange={handleSearch}
                    placeholder={t('chat.searchAssistantOrSkill')}
                    className="w-[600px] min-w-[300px] mt-[10px]"
                />
            </div>

            <div className="mt-[20px] px-12">
                <div className="flex flex-wrap">
                    {renderCategoryTags()}
                    {user.role === 'admin' && (
                        <SettingIcon
                            onClick={() => setIsLabelModalOpen(true)}
                            className="h-[30px] w-[30px] cursor-pointer"
                        />
                    )}
                </div>
            </div>

            <div className="relative overflow-y-auto h-[calc(100vh-308px)]">
                <div className="flex flex-wrap gap-2 px-12 scrollbar-hide pt-4 pb-20">
                    {renderChatOptions()}
                    {hasMoreData && <LoadMore onScrollLoad={handleLoadMore} />}
                </div>
            </div>

            <MarkLabel
                open={isLabelModalOpen}
                home={categoryTags}
                onClose={handleCloseLabelModal}
            />
        </div>
    )
}

const HeaderSection = ({ BASE_IMAGE_URL, t }) => (
    <div className="flex justify-center place-items-center gap-20">
        <img
            className="w-[138px]"
            src={`${BASE_IMAGE_URL}/application-start-logo.png`}
            alt="Application Logo"
        />
        <p className="text-2xl leading-[50px] dark:text-[#D4D4D4]">
            {t('chat.chooseOne')}
            <b className="dark:text-[#D4D4D4] font-semibold">{t('chat.dialogue')}</b>
            <br />
            {t('chat.start')}
            <b className="dark:text-[#D4D4D4] font-semibold">{t('chat.wenqingruijian')}</b>
        </p>
    </div>
)

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