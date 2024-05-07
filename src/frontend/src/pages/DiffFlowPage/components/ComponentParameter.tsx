import CodeAreaComponent from "@/components/codeAreaComponent";
import Dropdown from "@/components/dropdownComponent";
import FloatComponent from "@/components/floatComponent";
import InputComponent from "@/components/inputComponent";
import InputFileComponent from "@/components/inputFileComponent";
import InputListComponent from "@/components/inputListComponent";
import IntComponent from "@/components/intComponent";
import PromptAreaComponent from "@/components/promptComponent";
import TextAreaComponent from "@/components/textAreaComponent";
import ToggleShadComponent from "@/components/toggleShadComponent";
import { useMemo } from "react";

/**
 * 组件中的填写参数罗列
 * 参数模板 template
 */
export default function ComponentParameter({ disabled = false, flow, node, template, children, onChange = () => { } }) {
    const _disabled = false // disabled || (flow.data.edges.some((e) => e.targetHandle === node.id) ?? false);

    const keys = useMemo(() => {
        return Object.keys(template).filter(
            (t) =>
                t.charAt(0) !== "_" &&
                template[t].show &&
                (template[t].type === "str" ||
                    template[t].type === "bool" ||
                    template[t].type === "float" ||
                    template[t].type === "code" ||
                    template[t].type === "prompt" ||
                    template[t].type === "file" ||
                    template[t].type === "int" ||
                    template[t].type === "dict")
        )
    }, [template])

    const handleOnNewValue = (newValue: any, name) => {
        // console.log('object :>> ', object);
        // 引用更新
        node.data.node.template[name].value = newValue;
        // 手动修改知识库，collection_id 清空
        if (['index_name', 'collection_name'].includes(name)) delete node.data.node.template[name].collection_id
        onChange() // 更新通知
    }

    const getStrComp = (template, n) => {
        return template[n].list ? (
            <InputListComponent
                editNode={true}
                disabled={_disabled}
                value={
                    !template[n].value ||
                        template[n].value === ""
                        ? [""]
                        : template[n].value
                }
                onChange={(t: string[]) => {
                    handleOnNewValue(t, n);
                }}
            />
        ) : template[n].multiline ? (
            <TextAreaComponent
                disabled={_disabled}
                editNode={true}
                value={template[n].value ?? ""}
                onChange={(t: string) => {
                    handleOnNewValue(t, n);
                }}
            />
        ) : (
            <InputComponent
                editNode={true}
                disabled={_disabled}
                password={
                    template[n].password ?? false
                }
                value={template[n].value ?? ""}
                onChange={(t) => {
                    handleOnNewValue(t, n);
                }}
            />
        )
    }

    return <>
        {keys.map((n, i) => {
            const name = template[n].name || template[n].display_name

            if (template[n].type === "str") {
                if (template[n].options) {
                    return children(n, name, <Dropdown
                        numberOfOptions={keys.length}
                        editNode={true}
                        options={template[n].options}
                        onSelect={(t) => handleOnNewValue(t, n)}
                        value={
                            template[n].value ??
                            "Choose an option"
                        }
                    ></Dropdown>)
                } else {
                    return children(n, name, getStrComp(template, n))
                }
            }

            switch (template[n].type) {
                case "bool":
                    return children(n, name, <ToggleShadComponent
                        disabled={_disabled}
                        enabled={template[n].value}
                        setEnabled={(t) => {
                            handleOnNewValue(t, n);
                        }}
                        size="small"
                    />)
                case "float":
                    return children(n, name, <FloatComponent
                        disabled={_disabled}
                        editNode={true}
                        value={template[n].value ?? ""}
                        onChange={(t) => {
                            template[n].value = t;
                        }}
                    />)
                case "int":
                    return children(n, name, <IntComponent
                        disabled={_disabled}
                        editNode={true}
                        value={template[n].value ?? ""}
                        onChange={(t) => {
                            handleOnNewValue(t, n);
                        }}
                    />)
                case "file":
                    return children(n, name, <InputFileComponent
                        editNode={true}
                        disabled={_disabled}
                        value={template[n].value ?? ""}
                        onChange={(t: string) => {
                            handleOnNewValue(t, n);
                        }}
                        fileTypes={template[n].fileTypes}
                        suffixes={template[n].suffixes}
                        onFileChange={(t: string) => {
                            handleOnNewValue(t, n);
                        }}
                    ></InputFileComponent>)
                case "prompt":
                    return children(n, name, <PromptAreaComponent
                        field_name={n}
                        editNode={true}
                        disabled={_disabled}
                        nodeClass={node.data.node}
                        setNodeClass={(nodeClass) => {
                            node.data.node = nodeClass;
                        }}
                        value={template[n].value ?? ""}
                        onChange={(t: string) => {
                            handleOnNewValue(t, n);
                        }}
                    />)
                case "code":
                    return children(n, name, <CodeAreaComponent
                        disabled={_disabled}
                        editNode={true}
                        value={template[n].value ?? ""}
                        onChange={(t: string) => {
                            handleOnNewValue(t, n);
                        }}
                    />)
                case "Any": return children(n, name, "-")
                default: return children(n, name, <div className="hidden"></div>)
            }
        })
        }
    </>
};
