import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { userContext } from "@/contexts/userContext";
import { t } from "i18next";
import cloneDeep from "lodash-es/cloneDeep";
import { CircleX, Menu, Save } from "lucide-react";
import { useContext } from "react";
import DisclosureComponent from "../DisclosureComponent";

export default function PersonalComponents({ onDragStart }) {
    const { addSavedComponent, checkComponentsName, delComponent, savedComponents } = useContext(userContext)

    const addComponent = (data) => {
        if (checkComponentsName(data.node.display_name)) {
            bsConfirm({
                title: '组件已存在',
                desc: `组件 ${data.node.display_name} 已存在，覆盖原有组件还是继续创新建组件？`,
                showClose: true,
                okTxt: '覆盖',
                canelTxt: '创建新组建',
                onOk(next) {
                    addSavedComponent(cloneDeep(data), true)
                    next()
                },
                onCancel() {
                    addSavedComponent(cloneDeep(data), false)
                }
            })
        } else {
            addSavedComponent(cloneDeep(data), false, false)
        }
    }

    const upFile = () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".json";

        input.onchange = (e: Event) => {
            // check if the file type is application/json
            if (
                (e.target as HTMLInputElement).files[0].type === "application/json"
            ) {
                const currentfile = (e.target as HTMLInputElement).files[0];
                // read the file as text
                currentfile.text().then((text) => {
                    const data = JSON.parse(text);
                    if (!data.type) return
                    addComponent(data)
                });
            }
        };
        // trigger the file input click event to open the file dialog
        input.click();
    }

    const handleDel = (e, comp) => {
        e.stopPropagation()
        delComponent(comp.name)
    }

    return <TooltipProvider delayDuration={0} skipDelayDuration={200}>
        <Tooltip>
            <TooltipTrigger>
                <DisclosureComponent
                    openDisc={true}
                    button={{
                        title: t('skills.save'),
                        Icon: Save,
                        color: ''
                    }}
                > </DisclosureComponent>
            </TooltipTrigger>
            <TooltipContent className="bg-gray-0 rounded-md " side="right" collisionPadding={20}>
                <div className="">
                    <Button variant="outline" className="w-full rounded-full" onClick={upFile}>{t('skills.importLocal')}</Button>
                </div>
                <div className="max-h-[540px] overflow-y-auto no-scrollbar">
                    {
                        savedComponents.map(comp => (
                            <div key={comp.name}>
                                <div key={comp.name} data-tooltip-id={comp.name}>
                                    <div draggable
                                        className="side-bar-components-border bg-background mt-1 rounded-full border-l-red-500"
                                        onDragStart={(event) => onDragStart(event, comp.data)}
                                        onDragEnd={() => {
                                            document.body.removeChild(
                                                document.getElementsByClassName("cursor-grabbing")[0]
                                            );
                                        }}
                                    >
                                        <div className="side-bar-components-div-form border-solid rounded-full">
                                            <span className="side-bar-components-text max-w-40"> {comp.name} </span>
                                            <Menu className="side-bar-components-icon " />
                                            <CircleX className="side-bar-components-icon ml-2 cursor-pointer" onClick={(e) => handleDel(e, comp)} />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))
                    }
                </div>
            </TooltipContent>
        </Tooltip>
    </TooltipProvider>
}