import { LabelIcon } from "@/components/bs-icons/label";
import LabelSelect from "../selectComponent/LabelSelect";
import { UPDATETYPE } from "../selectComponent/LabelSelect";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BookmarkFilledIcon } from "@radix-ui/react-icons";

export default function LabelShow({ show, isOperator, labels, all, resource }) {
  const { t } = useTranslation()
  const [freshData, setFreshData] = useState(labels)
  const [allData, setAllData] = useState(all)
  const [isShow, setIsShow] = useState(show)

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
        break
      }
      case UPDATETYPE.CREATELABEL: {
        // 什么也不用做
        break
      }
      case UPDATETYPE.DELETELABEL: {
        setFreshData(pre => pre.filter(d => d.value !== obj.data.value))
        setAllData(pre => pre.filter(a => a.value !== obj.data.value))
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
              <BookmarkFilledIcon className="mr-2 text-muted-foreground" />
              <div className="text-sm text-muted-foreground max-w-[250px] truncate">
                {freshData.map((l, index) => <span>{l.label}{index !== freshData.length - 1 && '，'}</span>)}
              </div>
            </div>
          </LabelSelect>
        ) : (
          <div className="mb-[10px] flex place-items-center max-w-[100%] rounded-sm p-1">
            <BookmarkFilledIcon className="mr-2 text-muted-foreground" />
            <div className="text-sm text-muted-foreground max-w-[250px] truncate">
              {freshData.map((l, index) => <span>{l.label}{index !== freshData.length - 1 && '，'}</span>)}
            </div>
          </div>
        )
      ) : (
        isOperator ? (
          <LabelSelect onUpdate={handleUpdate} labels={labels} resource={resource} all={allData}>
            <div onClick={(e) => e.stopPropagation()} className="mb-[10px] flex place-items-center rounded-sm p-1 opacity-0 border border-transparent group-hover:bg-search-input group-hover:border-input group-hover:opacity-100">
              <BookmarkFilledIcon className="mr-2 text-muted-foreground" />
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
