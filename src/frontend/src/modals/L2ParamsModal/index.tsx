import { PenLine } from "lucide-react";
import { useContext, useRef, useState } from "react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../../components/ui/accordion";
import { Button } from "../../components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "../../components/ui/dialog";
import { Switch } from "../../components/ui/switch";
import { PopUpContext } from "../../contexts/popUpContext";
import { TabsContext } from "../../contexts/tabsContext";
import { typesContext } from "../../contexts/typesContext";
import { TemplateVariableType } from "../../types/api";
import { FlowType } from "../../types/flow";
import { classNames } from "../../utils";

const Item = ({ name, data }: { name: string, data: TemplateVariableType }) => {
    const [val, setVal] = useState(data.l2_name || name)
    const [edit, setEdit] = useState(false)

    const handleChange = (e) => {
        setVal(e.target.value)
        data.l2_name = e.target.value
    }

    const [_, forceupdate] = useState(1) // refrensh
    const handleSwitch = () => {
        data.l2 = !data.l2
        forceupdate(Math.random)
    }

    return <div className={`l2Param flex justify-between rounded-xl px-2 py-1 mb-2 ${data.l2 ? 'bg-gray-400 dark:bg-gray-100' : 'bg-gray-100 dark:bg-gray-500'}`}>
        {
            edit ? <div className="">
                <input type="text" value={val} onChange={handleChange} onKeyDown={e => e.key === 'Enter' && setEdit(false)}
                    className="flex h-6 w-full rounded-xl border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50" />
            </div> :
                <div className="flex items-center text-gray-900">
                    <span>{val}</span>
                    <button className="l2Param-edit transition-all" title="修改别名" onClick={() => setEdit(true)}><PenLine size={18} className="ml-2 cursor-pointer" /></button>
                </div>
        }
        <Switch id="airplane-mode" checked={data.l2} onCheckedChange={handleSwitch} />
    </div>
}

export default function L2ParamsModal({ data: flow, open, setOpen, onSave }: { data: FlowType } & any) {

    const [nodeValue, setNodeValue] = useState(null);
    const { closePopUp } = useContext(PopUpContext);
    const { types } = useContext(typesContext);
    const ref = useRef();
    const { setTabsState, tabId } = useContext(TabsContext);
    const { reactFlowInstance } = useContext(typesContext);

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild></DialogTrigger>
            <DialogContent className="sm:max-w-[600px] lg:max-w-[700px]">
                <DialogHeader>
                    <DialogTitle className="flex items-center">
                        <span className="pr-2">简化配置</span>
                    </DialogTitle>
                    <DialogDescription asChild>
                        <div>
                            您可以在此设置技能所需的最小参数集
                            <div className="flex pt-3">
                                {/* <Variable className="edit-node-modal-variable "></Variable> */}
                                <span className="edit-node-modal-span">参数列表</span>
                            </div>
                        </div>
                    </DialogDescription>
                </DialogHeader>

                <div className="edit-node-modal-arrangement">
                    <div
                        className={classNames(
                            "edit-node-modal-box", "overflow-scroll overflow-x-hidden custom-scroll h-[400px]"
                        )}
                    >
                        <Accordion type="multiple" defaultChecked>
                            {flow.data?.nodes.map(node => (
                                <AccordionItem key={node.id} value={node.id} className="px-6">
                                    <AccordionTrigger>{`${node.data.type}(${node.id})`}</AccordionTrigger>
                                    <AccordionContent>
                                        {Object.keys(node.data.node.template).map(k => {
                                            const template = node.data.node.template[k]
                                            const { type } = template
                                            return template.show && (type === "str" ||
                                                type === "bool" ||
                                                type === "float" ||
                                                type === "code" ||
                                                type === "prompt" ||
                                                type === "file" ||
                                                type === "int") && <Item key={k} name={k} data={node.data.node.template[k]}></Item>
                                        }
                                        )}
                                    </AccordionContent>
                                </AccordionItem>
                            ))}
                        </Accordion>
                    </div>
                </div>
                <DialogFooter>
                    <Button className="mt-3 rounded-full" onClick={() => { setOpen(false); onSave() }} type="submit" >保存配置</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
