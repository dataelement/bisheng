import cloneDeep from "lodash-es/cloneDeep";
import { ExternalLink, Plus, X } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { alertContext } from "../../contexts/alertContext";
import { Variable, VariableType, delVariableApi, getVariablesApi, saveVariableApi } from "../../controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { generateUUID } from "../../utils";
import { Dialog } from "../bs-ui/dialog";
import VarDialog from "./VarDialog";

/**
 * @component 变量编辑，分文本和options类型
 * @description
 * 维护一个变量的列表。
 * 通过 nodeId 获取该组件的变量集合，支持增删改
 * 通过子组件VarDialog编辑每一项
 */

export default function VariablesComponent({ vid, nodeId, flowId, onChange }: {
    vid: number
    nodeId: string
    flowId: string
    onChange: (val: any) => void
}) {
    const [items, setItems] = useState<Variable[]>([])

    useEffect(() => {
        // api nodeId -> items
        flowId && vid && getVariablesApi({
            version_id: vid,
            flow_id: flowId,
            node_id: nodeId
        }).then(arr => setItems(arr))
    }, [flowId, vid])

    const [openPop, setOpenPop] = useState(false)
    const { setErrorData } = useContext(alertContext);

    const { t } = useTranslation()

    // save
    const handleSave = async (_item) => {
        if (!_item.name) {
            return setErrorData({
                title: t('prompt'),
                list: [t('flow.enterVarName')]
            });
        }
        // 重名校验
        const hasName = items.find(item => item.name === _item.name)
        if (hasName && hasName.id !== _item.id) {
            return setErrorData({
                title: t('prompt'),
                list: [t('flow.varNameExists')],
            });
        }

        setOpenPop(false)
        // api
        const param: any = {
            "flow_id": flowId,
            "node_id": nodeId,
            version_id: vid,
            "variable_name": _item.name,
            "value_type": Number(_item.type === VariableType.Select) + 1,
            "value": _item.type === VariableType.Text ? _item.maxLength : _item.options.map(el => el.value).join(',')
        }
        if (_item.update) {
            param.id = _item.id
        }
        captureAndAlertRequestErrorHoc(saveVariableApi(param).then(res => {
            const _items = items.map(item => item.id === _item.id ? { ..._item, id: res.id, update: true } : item)
            // const hasValue = _items.find(item => item.name)
            // 保存时 id传出去保存，用来校验必填项
            onChange(_items.map(el => el.name))
            setItems(_items)
        }))
    }

    // 
    const handleDelClick = async (index) => {
        let newItems = cloneDeep(items);
        const item = newItems.splice(index, 1);
        item[0].update && await captureAndAlertRequestErrorHoc(delVariableApi(item[0].id))
        setItems(newItems)
        // 触发必填校验
        !newItems.length && onChange('')
    }

    // list超出滚动，配合template-scrollbar使用（TODO 抽象为插槽）
    const scrollBodyRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const scrollFun = (event) => {
            // 双指缩放 event.ctrlKey为 true
            if (!event.ctrlKey) {
                event.stopPropagation();
            }
        }
        scrollBodyRef.current.addEventListener('wheel', scrollFun);
        return () => scrollBodyRef.current?.removeEventListener('wheel', scrollFun);
    }, [])

    return (
        <div ref={scrollBodyRef} className="flex flex-col gap-3 template-scrollbar" >
            {items.map((item, idx) => {
                return (
                    <div key={idx} className="flex w-full gap-3">
                        <div className="input-primary min-h-8" onClick={() => setOpenPop(true)}>{item.name}</div>
                        <button  onClick={() => setOpenPop(true)}><ExternalLink className={"h-4 w-4 hover:text-accent-foreground"} /></button>
                        <Dialog open={openPop} onOpenChange={setOpenPop}>
                            <VarDialog data={item} onSave={handleSave} onClose={setOpenPop} />
                        </Dialog>
                        <button onClick={() => handleDelClick(idx)} >
                            <X className={"h-4 w-4 hover:text-accent-foreground"} />
                        </button>
                    </div>
                );
            })}
            <button
                onClick={() => {
                    setItems((old) => {
                        let newItems = cloneDeep(old);
                        newItems.push({
                            id: generateUUID(8),
                            name: "",
                            maxLength: 50,
                            type: VariableType.Text,
                            update: false,
                            options: [{
                                key: generateUUID(4),
                                value: ""
                            }],
                            nodeId,
                            required: false
                        });
                        return newItems;
                    });
                }}
            >
                <Plus className={"h-4 w-4 hover:text-accent-foreground"} />
            </button>
        </div >
    );
}
