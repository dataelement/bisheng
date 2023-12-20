import { useContext, useState } from "react";
import CodeAreaComponent from "../../../../components/codeAreaComponent";
import DictComponent from "../../../../components/dictComponent";
import Dropdown from "../../../../components/dropdownComponent";
import FloatComponent from "../../../../components/floatComponent";
import InputComponent from "../../../../components/inputComponent";
import InputFileComponent from "../../../../components/inputFileComponent";
import InputListComponent from "../../../../components/inputListComponent";
import IntComponent from "../../../../components/intComponent";
import KeypairListComponent from "../../../../components/keypairListComponent";
import PromptAreaComponent from "../../../../components/promptComponent";
import TextAreaComponent from "../../../../components/textAreaComponent";
import ToggleShadComponent from "../../../../components/toggleShadComponent";
import { TabsContext } from "../../../../contexts/tabsContext";
import { typesContext } from "../../../../contexts/typesContext";
import CollectionNameComponent from "../../../../pages/FlowPage/components/CollectionNameComponent";
import { cleanEdges, convertObjToArray, convertValuesToNumbers, hasDuplicateKeys } from "../../../../util/reactflowUtils";

export default function L2ParameterComponent({
    // id,
    data,
    type,
    name = "",
}) {
    const { reactFlowInstance } = useContext(typesContext);
    // let disabled = reactFlowInstance?.getEdges().some((e) => e.targetHandle === id) ?? false;
    let disabled = false

    const [errorDuplicateKey, setErrorDuplicateKey] = useState(false);

    const { setTabsState, tabId, save } = useContext(TabsContext);
    const handleOnNewValue = (newValue: any) => {
        data.node.template[name].value = ['float', 'int'].includes(type) ? Number(newValue) : newValue;
        // Set state to pending
        setTabsState((prev) => {
            return {
                ...prev,
                [tabId]: {
                    ...prev[tabId],
                    isPending: true,
                },
            };
        });
    };

    // 临时处理知识库保存方法, 类似方法多了需要抽象
    const handleOnNewLibValue = (newValue: string, collectionId: number | '') => {
        data.node.template[name].value = newValue;
        data.node.template[name].collection_id = collectionId;
        // Set state to pending
        setTabsState((prev) => {
            return {
                ...prev,
                [tabId]: {
                    ...prev[tabId],
                    isPending: true,
                },
            };
        });
    };
    return <div className="flex w-full flex-wrap items-center justify-between py-2 col-span-2" >
        {type === "str" &&
            !data.node.template[name].options ? (
            <div className="mt-2 w-full">
                {data.node.template[name].list ? (
                    <InputListComponent
                        disabled={disabled}
                        value={
                            !data.node.template[name].value ||
                                data.node.template[name].value === ""
                                ? [""]
                                : data.node.template[name].value
                        }
                        onChange={handleOnNewValue}
                    />
                ) : data.node.template[name].multiline ? (
                    <TextAreaComponent
                        disabled={disabled}
                        value={data.node.template[name].value ?? ""}
                        onChange={handleOnNewValue}
                    />
                ) : ['index_name', 'collection_name'].includes(name) ? (
                    // 知识库选择
                    <CollectionNameComponent
                        setNodeClass={(nodeClass) => {
                            data.node = nodeClass;
                        }}
                        nodeClass={data.node}
                        disabled={disabled}
                        id={data.node.template[name].collection_id ?? ""}
                        value={data.node.template[name].value ?? ""}
                        onSelect={handleOnNewLibValue}
                        onChange={() => {}}
                    />
                ) : (
                    <InputComponent
                        disabled={disabled}
                        disableCopyPaste={true}
                        password={data.node.template[name].password ?? false}
                        value={data.node.template[name].value ?? ""}
                        onChange={handleOnNewValue}
                    />
                )}
            </div>
        ) : type === "bool" ? (
            <div className="mt-2 w-full">
                <ToggleShadComponent
                    disabled={disabled}
                    enabled={data.node.template[name].value}
                    setEnabled={(t) => {
                        handleOnNewValue(t);
                    }}
                    size="large"
                />
            </div>
        ) : type === "float" ? (
            <div className="mt-2 w-full">
                <FloatComponent
                    disabled={disabled}
                    disableCopyPaste={true}
                    value={data.node.template[name].value ?? ""}
                    onChange={handleOnNewValue}
                />
            </div>
        ) : type === "str" &&
            data.node.template[name].options ? (
            <div className="mt-2 w-full">
                <Dropdown
                    options={data.node.template[name].options}
                    onSelect={handleOnNewValue}
                    value={data.node.template[name].value ?? "choose option"}
                ></Dropdown>
            </div>
        ) : type === "code" ? (
            <div className="mt-2 w-full">
                <CodeAreaComponent
                    setNodeClass={(nodeClass) => {
                        data.node = nodeClass;
                    }}
                    nodeClass={data.node}
                    disabled={disabled}
                    value={data.node.template[name].value ?? ""}
                    onChange={handleOnNewValue}
                />
            </div>
        ) : type === "file" ? (
            <div className="mt-2 w-full">
                <InputFileComponent
                    disabled={disabled}
                    value={data.node.template[name].value ?? ""}
                    onChange={handleOnNewValue}
                    fileTypes={data.node.template[name].fileTypes}
                    suffixes={data.node.template[name].suffixes}
                    onFileChange={(t: string) => {
                        data.node.template[name].file_path = t;
                        save();
                    }}
                ></InputFileComponent>
            </div>
        ) : type === "int" ? (
            <div className="mt-2 w-full">
                <IntComponent
                    disabled={disabled}
                    disableCopyPaste={true}
                    value={data.node.template[name].value ?? ""}
                    onChange={handleOnNewValue}
                />
            </div>
        ) : type === "prompt" ? (
            <div className="mt-2 w-full">
                <PromptAreaComponent
                    field_name={name}
                    setNodeClass={(nodeClass) => {
                        data.node = nodeClass;
                        if (reactFlowInstance) {
                            cleanEdges({
                                flow: {
                                    edges: reactFlowInstance.getEdges(),
                                    nodes: reactFlowInstance.getNodes(),
                                },
                                updateEdge: (edge) => reactFlowInstance.setEdges(edge),
                            });
                        }
                    }}
                    nodeClass={data.node}
                    disabled={disabled}
                    value={data.node.template[name].value ?? ""}
                    onChange={handleOnNewValue}
                />
            </div>
        ) : type === "NestedDict" ? (
            <div className="mt-2 w-full">
                <DictComponent
                    disabled={disabled}
                    editNode={false}
                    value={
                        !data.node!.template[name].value ||
                            data.node!.template[name].value?.toString() === "{}"
                            ? '{"yourkey": "value"}'
                            : data.node!.template[name].value
                    }
                    onChange={(newValue) => {
                        data.node!.template[name].value = newValue;
                        handleOnNewValue(newValue);
                    }}
                />
            </div>
        ) : type === "dict" ? (
            <div className="mt-2 w-full">
                <KeypairListComponent
                    disabled={disabled}
                    editNode={false}
                    value={
                        data.node!.template[name].value?.length === 0 ||
                            !data.node!.template[name].value
                            ? [{ "": "" }]
                            : convertObjToArray(data.node!.template[name].value)
                    }
                    duplicateKey={errorDuplicateKey}
                    onChange={(newValue) => {
                        const valueToNumbers = convertValuesToNumbers(newValue);
                        data.node!.template[name].value = valueToNumbers;
                        setErrorDuplicateKey(hasDuplicateKeys(valueToNumbers));
                        handleOnNewValue(valueToNumbers);
                    }}
                />
            </div>) : (
            <></>
        )}
    </div>
}