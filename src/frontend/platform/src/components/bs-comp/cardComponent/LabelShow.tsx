import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import LabelSelect, { UPDATETYPE } from "../selectComponent/LabelSelect";
import { Bookmark } from "lucide-react";

export default function LabelShow({ data, user, all, type, onChange }) {
  const { t } = useTranslation()
  const [freshData, setFreshData] = useState(() =>
    data.tags.map(d => ({ label: d.name, value: d.id, selected: true, edit: false }))
  )
  const labels = useMemo(() => {
    return data.tags.map(d => ({ label: d.name, value: d.id, selected: true, edit: false }))
  }, [data])

  const [allData, setAllData] = useState([])
  useEffect(() => {
    setAllData(all)
  }, [all])
  const [isShow, setIsShow] = useState(data.tags.length > 0)

  const resource = { id: data.id, type }

  const isOperator = useMemo(() => {
    if (data && user) {
      if (user.role === 'admin') return true
      data.group_ids.forEach(element => {
        if (user.admin_groups.includes(element)) return true
      })
      if (data.user_id === user.user_id) return true
    }
    return false
  }, [data, user])

  const handleUpdate = (obj: { type: string, data: any }) => {
    switch (obj.type) {
      case UPDATETYPE.DELETELINK: {
        setFreshData(pre => pre.filter(l => l.value !== obj.data.value))
        break
      }
      case UPDATETYPE.CREATELINK: {
        setFreshData(pre => [obj.data, ...pre])
        break
      }
      case UPDATETYPE.UPDATENAME: {
        setFreshData(pre => pre.map(d => d.value === obj.data.value ? { ...d, label: obj.data.label } : d))
        onChange()
        break
      }
      case UPDATETYPE.CREATELABEL: {
        onChange()
        break
      }
      case UPDATETYPE.DELETELABEL: {
        setFreshData(pre => pre.filter(d => d.value !== obj.data.value))
        onChange()
        // setAllData(pre => pre.filter(a => a.value !== obj.data.value))
        break
      }
      default: console.log('error：>>事件类型错误！！！')
    }
  }

  useEffect(() => {
    setIsShow(freshData.length > 0)
  }, [freshData])

  return (
    <div className="w-full">
      {isShow ? (
        isOperator ? (
          <LabelSelect onUpdate={handleUpdate} labels={labels} resource={resource} all={allData}>
            <div onClick={(e) => e.stopPropagation()} className="mb-[10px] max-w-[100%] flex place-items-center rounded-sm p-1 border border-transparent group-hover:bg-search-input group-hover:border-input">
              <Bookmark className="w-4 h-4 mr-2 text-muted-foreground" />
              <div className="text-sm text-muted-foreground max-w-[250px] truncate">
                {freshData.map((l, index) => <span>{l.label}{index !== freshData.length - 1 && '，'}</span>)}
              </div>
            </div>
          </LabelSelect>
        ) : (
          <div className="mb-[10px] flex place-items-center max-w-[100%] rounded-sm p-1">
            <Bookmark className="w-4 h-4 mr-2 text-muted-foreground" />
            <div className="text-sm text-muted-foreground max-w-[250px] truncate">
              {freshData.map((l, index) => <span>{l.label}{index !== freshData.length - 1 && '，'}</span>)}
            </div>
          </div>
        )
      ) : (
        isOperator ? (
          <LabelSelect onUpdate={handleUpdate} labels={labels} resource={resource} all={allData}>
            <div onClick={(e) => e.stopPropagation()} className="mb-[10px] flex place-items-center rounded-sm p-1 opacity-0 border border-transparent group-hover:bg-search-input group-hover:border-input group-hover:opacity-100">
              <Bookmark className="w-4 h-4 mr-2 text-muted-foreground" />
              <div className="text-sm text-muted-foreground">
                <span>{t('tag.addLabel')}</span>
              </div>
            </div>
          </LabelSelect>
        ) : (
          <div></div>
        )
      )}
    </div>
  )
}
