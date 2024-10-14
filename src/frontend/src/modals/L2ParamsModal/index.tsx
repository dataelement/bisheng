import { PenLine } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../../components/ui/accordion";
import { Button } from "../../components/bs-ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "../../components/bs-ui/dialog";
import { Label } from "../../components/bs-ui/label";
import { Switch } from "../../components/bs-ui/switch";
import { TemplateVariableType } from "../../types/api";
import { FlowType } from "../../types/flow";
import { classNames } from "../../utils";

const Item = ({ name, data }: { name: string, data: TemplateVariableType }) => {
    const { t } = useTranslation()

    const [val, setVal] = useState(data.l2_name || name);
    const [edit, setEdit] = useState(false);

    const handleChange = (e) => {
        setVal(e.target.value);
        data.l2_name = e.target.value;
    }

    const [_, forceupdate] = useState(1); // refresh
    const handleSwitch = () => {
        data.l2 = !data.l2;
        forceupdate(Math.random);
    }

    return (
        <div className={`l2Param flex justify-between rounded-xl px-2 py-1 mb-2 ${data.l2 ? 'bg-gray-400 dark:bg-gray-800' : 'bg-gray-100 dark:bg-gray-500'}`}>
            <div>
                <div className="flex items-center">
                    <Label className="pr-2">{t('flow.parameterLabel')}:</Label>
                    <span>{name}</span>
                </div>
                <div className="flex items-center">
                    <Label className="pr-2">{t('flow.aliasLabel')}:</Label>
                    {edit ?
                        <div className="">
                            <input
                                type="text"
                                value={val}
                                onChange={handleChange}
                                onKeyDown={(e) => e.key === 'Enter' && setEdit(false)}
                                className="flex h-6 w-full rounded-xl border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                            />
                        </div>
                        : <div className="flex items-center text-gray-900 dark:text-gray-300">
                            <span>{val}</span>
                            <button className="l2Param-edit transition-all" title={t('flow.editAlias')} onClick={() => setEdit(true)}>
                                <PenLine size={18} className="ml-2 cursor-pointer" />
                            </button>
                        </div>
                    }
                </div>
            </div>
            <Switch id="airplane-mode" checked={data.l2} onCheckedChange={handleSwitch} />
        </div>
    );
};


const ComponentItem = ({ id, data }) => {
    const { t } = useTranslation()

    const [val, setVal] = useState(data.node.l2_name || data.type);
    const [edit, setEdit] = useState(false);

    const handleChange = (e) => {
        setVal(e.target.value);
        data.node.l2_name = e.target.value;
    }

    return (
        <AccordionItem value={id} className="px-6">
            <AccordionTrigger>
                <div className="l2Param w-full">
                    <div className="flex items-center">
                        <Label className="pr-2">{t('flow.componentLabel')}:</Label>
                        <span>{`${data.type}(${id})`}</span>
                    </div>
                    <div className="flex items-center mt-1" onClick={(e) => e.stopPropagation()}>
                        <Label className="pr-2">{t('flow.aliasLabel')}:</Label>
                        {edit ? (
                            <div className="">
                                <input
                                    type="text"
                                    value={val}
                                    onChange={handleChange}
                                    onKeyDown={(e) => {
                                        e.key === 'Enter' && setEdit(false);
                                        e.code === 'Space' && e.preventDefault();
                                    }}
                                    className="flex h-6 w-full rounded-xl border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                                />
                            </div>
                        ) : (
                            <div className="flex items-center text-gray-900 dark:text-gray-300">
                                <span>{val}</span>
                                <button
                                    className="l2Param-edit transition-all"
                                    title={t('flow.editAlias')}
                                    onClick={() => setEdit(true)}
                                >
                                    <PenLine size={18} className="ml-2 cursor-pointer" />
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            </AccordionTrigger>
            <AccordionContent>
                {Object.keys(data.node.template).map(k => {
                    const template = data.node.template[k];
                    const { type } = template;
                    return template.show && (type === "str" ||
                        type === "bool" ||
                        type === "float" ||
                        type === "code" ||
                        type === "prompt" ||
                        type === "file" ||
                        type === "int") && <Item key={k} name={k} data={data.node.template[k]} />;
                })}
            </AccordionContent>
        </AccordionItem>
    );
};


export default function L2ParamsModal({ data: flow, open, setOpen, onSave }: { data: FlowType } & any) {
    const { t } = useTranslation()

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild></DialogTrigger>
            <DialogContent className="sm:max-w-[600px] lg:max-w-[700px]">
                <DialogHeader>
                    <DialogTitle className="flex items-center">
                        <span className="pr-2">{t('flow.simplifyConfig')}</span>
                    </DialogTitle>
                    <DialogDescription asChild>
                        <div>
                            {t('flow.minimumParamSetDescription')}
                            <div className="flex pt-3">
                                <span className="edit-node-modal-span">{t('flow.paramList')}</span>
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
                                <ComponentItem key={node.id} id={node.id} data={node.data}></ComponentItem>
                            ))}
                        </Accordion>
                    </div>
                </div>
                <DialogFooter>
                    <Button className="mt-3 rounded-full" onClick={() => { setOpen(false); onSave() }} type="submit" >{t('flow.saveConfig')}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}