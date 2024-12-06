import { Input } from "@/components/bs-ui/input";
import { readFileLibDatabase } from "@/controllers/API";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function SelectCollection({ collectionId, onChange }:
    { collectionId: number | '', onChange: (obj: any) => void }) {
    const { t } = useTranslation()

    const [datalist, setDataList] = useState([])
    const inputRef = useRef(null)
    const allData = useRef([])

    // Selected element at the top
    const libList = useMemo(() => {
        if (!datalist.length) return []
        const current = datalist.find(el => el.id === collectionId)
        if (!current) return datalist
        const cloneList = datalist.filter(el => el.id !== collectionId)
        return [current, ...cloneList]
    }, [datalist, collectionId])

    // 取800条 TODO 滚动分页 
    useEffect(() => {
        readFileLibDatabase(1, 800).then(res => {
            setDataList(res.data)
            allData.current = res.data
        })
    }, [])

    // 检索（暂无分页，本地search）
    const timerRef = useRef(null)
    const handleInputChange = (e) => {
        clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => {
            const value = e.target.value
            setDataList(allData.current.filter(item => item.name.indexOf(value) !== -1))
        }, 500);
    }

    return <div>
        <p className="my-4 font-bold">{t('flow.knowledgeBaseSelection')}</p>
        <Input placeholder={t('flow.searchKnowledgeBase')} ref={inputRef} onChange={handleInputChange} />
        <div className="mt-4 h-[280px] overflow-y-auto no-scrollbar">
            {libList.map(item =>
                <div
                    key={item.id}
                    className={`hover:bg-gray-100 cursor-pointer px-4 py-2 rounded-md ${item.id === collectionId && 'bg-gray-100'}`}
                    onClick={() => onChange(item)}
                >
                    <p className="text-sm">{item.name}</p>
                    <p className="text-xs text-gray-500">{item.collection_name}</p>
                </div>
            )}
        </div>
    </div>
};
