import { Switch } from "@/components/bs-ui/switch";
import { getVariablesApi, saveReportFormApi } from "@/controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronUp, ChevronsUpDown, FolderUp, GripVertical } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';
import { useTranslation } from "react-i18next";

/**
 * @component l2报表表单展示，可设置必填项及表单排序
 * @description
 * 表单项数据由组件的参数信息和单独接口获取的必填信息及排序信息而来。
 * 设置必填项及表单排序信息
 * change 保存信息到独立接口
 */

export default forwardRef(function FormSet({ id, vid }: any, ref) {
    const { t } = useTranslation()

    const showContent = (e) => {
        const target = e.target.tagName === 'svg' ? e.target.parentNode : e.target
        const contentDom = target.nextSibling
        target.children[0].style.transform = contentDom.clientHeight ? 'rotate(180deg)' : 'rotate(0deg)'
        contentDom.style.maxHeight = contentDom.clientHeight ? 0 : '999px'
    }

    // 从 api中获取
    const [items, setItems] = useState([])
    useEffect(() => {
        getVariablesApi({ version_id: vid, flow_id: id }).then(
            res => setItems(res)
        )
    }, [])

    // sort
    const handleDragEnd = ({ source, destination }: any) => {
        if (!destination) {
            return;
        }

        const updatedItems = Array.from(items);
        const [removed] = updatedItems.splice(source.index, 1);
        updatedItems.splice(destination.index, 0, removed);

        handleSave(updatedItems)
        setItems(updatedItems);
    };

    useImperativeHandle(ref, () => ({
        save: () => {
            saveFucRef.current()
        }
    }));
    // save
    const saveFucRef = useRef(() => { })
    const handleSave = (items) => {
        saveFucRef.current = () => {
            captureAndAlertRequestErrorHoc(saveReportFormApi(vid, id, items))
        }
    }

    return <div className="mt-8">
        <p className="text-center text-gray-400 mt-4 cursor-pointer flex justify-center" onClick={showContent}>{t('report.formSettings')}<ChevronUp /></p>
        <div className="overflow-hidden transition-all pl-8 px-1">
            <DragDropContext onDragEnd={handleDragEnd}>
                <Droppable droppableId={'list'} direction="vertical">
                    {(provided) => (
                        <ul
                            {...provided.droppableProps}
                            ref={provided.innerRef}
                        >
                            {items.map((item: any, index: number) => (
                                <Draggable key={'drag' + item.id} draggableId={'drag' + item.id} index={index}>
                                    {(provided) => (
                                        <div className="mt-4"
                                            ref={provided.innerRef}
                                            {...provided.draggableProps}>
                                            <div className="flex justify-between">
                                                <div className="flex gap-2 relative items-center">
                                                    <button {...provided.dragHandleProps} className="absolute left-[-26px]">
                                                        <GripVertical size={20} color="#999"></GripVertical>
                                                    </button>
                                                    <label className="font-medium text-sm max-w-[200px] truncate">{item.name}</label>
                                                    <p className="text-gray-500 text-sm">{item.nodeId}</p>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <label className="text-xs">{t('report.requiredLabel')}</label>
                                                    <Switch checked={item.type === 'file' || item.required} onCheckedChange={e => {
                                                        item.type !== 'file' && setItems(old => {
                                                            const _items = old.map(el => {
                                                                return el.id === item.id ? { ...el, required: e } : el
                                                            })
                                                            handleSave(_items)
                                                            return _items
                                                        })
                                                    }}></Switch>
                                                </div>
                                            </div>
                                            <div className="mt-2">
                                                {item.type === 'text' && <div className="cursor-pointer h-10 border rounded-sm"></div>}
                                                {item.type === 'select' && <div className="cursor-pointer h-10 border rounded-sm flex items-center justify-end px-2">
                                                    <ChevronsUpDown className="dropdown-component-arrow-color" />
                                                </div>}
                                                {item.type === 'file' && <div className="cursor-pointer flex h-16 justify-center items-center border rounded-sm">
                                                    <FolderUp />
                                                </div>}
                                            </div>
                                        </div>
                                    )}
                                </Draggable>
                            ))}
                            {provided.placeholder}
                        </ul>
                    )}
                </Droppable>
            </DragDropContext>
        </div>
    </div>
});
