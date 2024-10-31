import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge";
import ModelSelect from "@/pages/BuildPage/assistant/editAssistant/ModelSelect";
import CollectionNameComponent from "@/pages/BuildPage/skills/editSkill/CollectionNameComponent";
import cloneDeep from "lodash-es/cloneDeep";
import { Info } from "lucide-react";
import React, { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Handle, Position, useUpdateNodeInternals } from "@xyflow/react";
import ShadTooltip from "../../../../components/ShadTooltipComponent";
import VariablesComponent from "../../../../components/VariablesComponent";
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
import { PopUpContext } from "../../../../contexts/popUpContext";
import { TabsContext } from "../../../../contexts/tabsContext";
import { typesContext } from "../../../../contexts/typesContext";
import { reloadCustom } from "../../../../controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "../../../../controllers/request";
import { ParameterComponentType } from "../../../../types/components";
import { cleanEdges, convertObjToArray, convertValuesToNumbers, hasDuplicateKeys } from "../../../../util/reactflowUtils";
import {
  classNames,
  getNodeNames,
  groupByFamily,
  isValidConnection,
  nodeColors,
  nodeIconsLucide
} from "../../../../utils";

export default function ParameterComponent({
  left,
  id,
  data,
  tooltipTitle,
  title,
  color,
  type,
  name = "",
  required = false,
  optionalHandle = null,
  info = "",
  isGroup = false,
  onChange
}: ParameterComponentType) {
  // console.log('data, id :>> ', name, optionalHandle);
  const { id: flowId } = useParams();

  const ref = useRef(null);
  const refHtml = useRef(null);
  const refNumberComponents = useRef(0);
  const infoHtml = useRef(null);
  const updateNodeInternals = useUpdateNodeInternals();
  const [position, setPosition] = useState(0);
  const { closePopUp } = useContext(PopUpContext);
  const { setTabsState, flow, version } = useContext(TabsContext);

  const groupedEdge = useRef(null); // 用yu过滤菜单的数据

  useEffect(() => {
    if (ref.current && ref.current.offsetTop && ref.current.clientHeight) {
      setPosition(ref.current.offsetTop + ref.current.clientHeight / 2);
      updateNodeInternals(data.id);
    }
  }, [data.id, ref, ref.current, ref.current?.offsetTop, updateNodeInternals]);

  useEffect(() => {
    updateNodeInternals(data.id);
  }, [data.id, position, updateNodeInternals]);

  useEffect(() => { }, [closePopUp, data.node.template]);

  const { reactFlowInstance } = useContext(typesContext);
  const disabled = useMemo(() => {
    let dis = reactFlowInstance?.getEdges().some((e) => e.targetHandle === id) ?? false;
    // 特殊处理含有知识库组件的 disabled
    if (['index_name', 'collection_name'].includes(name)
      && reactFlowInstance?.getEdges().some((e) => e.targetHandle.indexOf('documents') !== -1
        && e.targetHandle.indexOf(data.id) !== -1)) {
      dis = true
    }
    return dis
  }, [id, data, reactFlowInstance])
  // milvus 组件，知识库不为空是 embbeding取消必填限制
  useEffect(() => {
    const { embedding, index_name, collection_name, connection_args } = data.node.template
    if ((index_name || collection_name) && embedding) {
      const hidden = disabled ? false : !!(collection_name || index_name).value
      data.node.template.embedding.required = !hidden
      data.node.template.embedding.show = !hidden
      if (hidden && connection_args) data.node.template.connection_args.value = ''
      onChange?.()
    }
  }, [data, disabled])
  const handleRemoveMilvusEmbeddingEdge = (nodeId) => {
    const edges = reactFlowInstance.getEdges().filter(edge => edge.targetHandle.indexOf('Embeddings|embedding|' + nodeId) === -1)
    reactFlowInstance.setEdges(edges)
  }
  const [myData, setMyData] = useState(useContext(typesContext).data);

  const handleOnNewValue = useCallback((newValue: any) => {
    // TODO 使用setNodes 保存修改（onChange）
    data.node.template[name].value = ['float', 'int'].includes(type) ? Number(newValue) : newValue;
    // Set state to pending
    setTabsState((prev) => {
      return {
        ...prev,
        [flow.id]: {
          ...prev[flow.id],
          isPending: true,
        },
      };
    });
  }, [data, flow.id]);

  // 临时处理知识库保存方法, 类似方法多了需要抽象
  const handleOnNewLibValue = (newValue: string, collectionId: number | '') => {
    // TODO 使用setNodes 保存修改（onChange）
    data.node.template[name].value = newValue;
    data.node.template[name].collection_id = collectionId;
    // Set state to pending
    setTabsState((prev) => {
      return {
        ...prev,
        [flow.id]: {
          ...prev[flow.id],
          isPending: true,
        },
      };
    });
  };

  // custom 组件 reload
  const handleReloadCustom = (code) => {
    captureAndAlertRequestErrorHoc(reloadCustom(code)).then(res => {
      if (res) {
        reactFlowInstance.setNodes((nds) =>
          nds.map((nd) => {
            if (nd.id === data.id) {
              let newNode = cloneDeep(nd);
              newNode.data.node = res
              return newNode;
            }
            return nd
          })
        )
        // 清理线
        setTimeout(() => {
          const edges = cleanEdges(
            reactFlowInstance.getNodes(),
            reactFlowInstance.getEdges()
          )
          reactFlowInstance.setEdges(edges)
        }, 60);
      }
    })
  }

  useEffect(() => {
    infoHtml.current = (
      <div className="h-full w-full break-words">
        {info.split("\n").map((line, i) => (
          <p key={i} className="block">
            {line}
          </p>
        ))}
      </div>
    );
  }, [info]);

  const [errorDuplicateKey, setErrorDuplicateKey] = useState(false);

  useEffect(() => {
    let groupedObj: any = groupByFamily(myData, tooltipTitle!, left, flow.data?.nodes || []);
    groupedEdge.current = groupedObj;

    if (groupedObj && groupedObj.length > 0) {
      //@ts-ignore
      refHtml.current = groupedObj.map((item, index) => {
        const Icon: any =
          nodeIconsLucide[item.family] ?? nodeIconsLucide["unknown"];

        return (
          <div key={index}>
            {index === 0 && (
              <span>
                {left
                  ? "Avaliable input components:"
                  : "Avaliable output components:"}
              </span>
            )}
            <span
              key={index}
              className={classNames(
                index > 0 ? "mt-2 flex items-center" : "mt-3 flex items-center"
              )}
            >
              <div
                className="h-5 w-5"
                style={{
                  color: nodeColors[item.family],
                }}
              >
                <Icon
                  className="h-5 w-5"
                  strokeWidth={1.5}
                  style={{
                    color: nodeColors[item.family] ?? nodeColors.unknown,
                  }}
                />
              </div>
              <span className="ps-2 text-xs text-foreground">
                {getNodeNames()[item.family] ?? "Other"}{" "}
                {item?.display_name && item?.display_name?.length > 0 ? (
                  <span className="text-xs">
                    {" "}
                    {item.display_name === "" ? "" : " - "}
                    {item.display_name.split(", ").length > 2
                      ? item.display_name.split(", ").map((el, index) => (
                        <React.Fragment key={el + index}>
                          <span>
                            {index ===
                              item.display_name.split(", ").length - 1
                              ? el
                              : (el += `, `)}
                          </span>
                        </React.Fragment>
                      ))
                      : item.display_name}
                  </span>
                ) : (
                  <span className="text-xs">
                    {" "}
                    {item.type === "" ? "" : " - "}
                    {item.type.split(", ").length > 2
                      ? item.type.split(", ").map((el, index) => (
                        <React.Fragment key={el + index}>
                          <span>
                            {index === item.type.split(", ").length - 1
                              ? el
                              : (el += `, `)}
                          </span>
                        </React.Fragment>
                      ))
                      : item.type}
                  </span>
                )}
              </span>
            </span>
          </div>
        );
      });
    } else {
      //@ts-ignore
      refHtml.current = <span>No compatible components found.</span>;
    }
  }, [tooltipTitle]);

  return (
    <div
      ref={ref}
      className="flex w-full flex-wrap items-center justify-between bg-muted px-5 py-2"
    >
      <>
        <div
          className={
            "w-full truncate text-sm" +
            (left ? "" : " text-end") +
            (info !== "" ? " flex items-center" : "")
          }
        >
          {title}
          <span className="text-status-red">{required ? " *" : ""}</span>
          <div className="">
            {info !== "" && (
              <ShadTooltip content={infoHtml.current}>
                <Info className="relative bottom-0.5 ml-2 h-3 w-3" />
              </ShadTooltip>
            )}
          </div>
        </div>
        {/* 触点 */}
        {left &&
          (type === "str" ||
            type === "bool" ||
            type === "float" ||
            type === "code" ||
            type === "prompt" ||
            type === "file" ||
            type === "int" ||
            type === "variable" ||
            type === "button" ||
            type === "knowledge_one" ||
            type === "knowledge_list" ||
            type === "NestedDict" ||
            type === "dict" ||
            type === "bisheng_model" ||
            type === "bisheng_embedding") &&
          !optionalHandle ? (<></>)
          : (
            <ShadTooltip
              styleClasses={"tooltip-fixed-width custom-scroll nowheel"}
              delayDuration={0}
              content={refHtml.current}
              side={left ? "left" : "right"}
            >
              <Handle
                type={left ? "target" : "source"}
                position={left ? Position.Left : Position.Right}
                id={id}
                isValidConnection={(connection) =>
                  isValidConnection(connection, reactFlowInstance)
                }
                className={classNames(
                  left ? "-ml-0.5 " : "-mr-0.5 ",
                  "h-3 w-3 rounded-full border-2 bg-background"
                )}
                style={{
                  borderColor: color,
                  top: position,
                }}
              ></Handle>
            </ShadTooltip>
          )}

        {/* 左侧input输入项 */}
        {!data.node.template[name] ? null : left === true &&
          type === "str" &&
          !data.node.template[name].options ? (
          <div className="mt-2 w-full">
            {data.node.template[name].list ? (
              // input list
              <InputListComponent
                isGroup={isGroup}
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
              // 多行数如
              <TextAreaComponent
                disabled={disabled}
                value={data.node.template[name].value ?? ""}
                onChange={handleOnNewValue}
              />
            ) : ['index_name', 'collection_name'].includes(name) ? (
              // 知识库选择
              <CollectionNameComponent
                disabled={disabled}
                id={data.node.template[name].collection_id ?? ""}
                value={data.node.template[name].value ?? ""}
                onSelect={(val, id) => { handleOnNewLibValue(val, id); val && handleRemoveMilvusEmbeddingEdge(data.id) }}
                onChange={() => { }}
              />
            ) : (
              // 单行输入
              <InputComponent
                disabled={disabled}
                password={data.node.template[name].password ?? false}
                value={data.node.template[name].value ?? ""}
                onChange={handleOnNewValue}
              />
            )}
          </div>
        ) : left === true && type === "knowledge_one" ? (
          // 单选知识库
          <div className="mt-2 w-full">
            <CollectionNameComponent
              disabled={disabled}
              id={data.node.template[name].collection_id ?? ""}
              value={data.node.template[name].value ?? ""}
              onSelect={(val, id) => { handleOnNewLibValue(val, id); val && handleRemoveMilvusEmbeddingEdge(data.id) }}
              onChange={() => { }}
            />
          </div>
        ) : left === true && type === "knowledge_list" ? (
          // 多选知识库
          <div className="mt-2 w-full">
            <KnowledgeSelect
              multiple
              disabled={disabled}
              value={data.node.template[name].value?.map?.((item) => ({
                label: item.value,
                value: item.key,
              })) || []}
              onChange={(vals) => {
                handleOnNewValue(vals.map(v => ({
                  key: v.value,
                  value: v.label
                })))
              }}
            />
          </div>
        ) : left === true && type === "bool" ? (
          <div className="mt-2 w-full">
            {/* switch */}
            <ToggleShadComponent
              disabled={disabled}
              enabled={data.node.template[name].value}
              setEnabled={(t) => {
                handleOnNewValue(t);
              }}
              size="large"
            />
          </div>
        ) : left === true && type === "float" ? (
          <div className="mt-2 w-full">
            <FloatComponent
              disabled={disabled}
              value={data.node.template[name].value ?? ""}
              onChange={handleOnNewValue}
            />
          </div>
        ) : left === true &&
          type === "str" &&
          data.node.template[name].options ? (
          // 下拉框
          <div className="mt-2 w-full">
            <Dropdown
              options={data.node.template[name].options}
              onSelect={handleOnNewValue}
              value={data.node.template[name].value ?? "Choose an option"}
            ></Dropdown>
          </div>
        ) : left === true && type === "code" ? (
          <div className="mt-2 w-full">
            <CodeAreaComponent
              setNodeClass={(nodeClass) => {
                data.node = nodeClass; // 无用
              }}
              nodeClass={data.node}
              disabled={disabled}
              value={data.node.template[name].value ?? ""}
              onChange={data.type === 'Data' ? handleReloadCustom : handleOnNewValue}
            />
          </div>
        ) : left === true && type === "file" ? (
          <div className="mt-2 w-full">
            <InputFileComponent
              disabled={disabled}
              value={data.node.template[name].value ?? ""}
              onChange={handleOnNewValue}
              fileTypes={data.node.template[name].fileTypes}
              suffixes={data.node.template[name].suffixes}
              onFileChange={(t: string) => {
                data.node.template[name].file_path = t;
                // save();
              }}
            ></InputFileComponent>
          </div>
        ) : left === true && type === "int" ? (
          <div className="mt-2 w-full">
            <IntComponent
              disabled={disabled}
              value={data.node.template[name].value ?? ""}
              onChange={handleOnNewValue}
            />
          </div>
        ) : left === true && type === "prompt" ? (
          <div className="mt-2 w-full">
            <PromptAreaComponent
              field_name={name}
              setNodeClass={(nodeClass, code) => {
                if (reactFlowInstance) {
                  reactFlowInstance.setNodes((nds) =>
                    nds.map((nd) => {
                      if (nd.id === data.id) {
                        let newNode = cloneDeep(nd);
                        newNode.data.node = nodeClass
                        newNode.data.node.template[name].value = code;
                        return newNode;
                      }
                      return nd
                    })
                  )
                  // 清理线
                  setTimeout(() => {
                    const edges = cleanEdges(
                      reactFlowInstance.getNodes(),
                      reactFlowInstance.getEdges()
                    )
                    reactFlowInstance.setEdges(edges)
                  }, 60);
                }
              }}
              nodeClass={data.node}
              disabled={disabled}
              value={data.node.template[name].value ?? ""}
              onChange={handleOnNewValue}
            />
          </div>
        ) : left === true && type === "NestedDict" ? (
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
        ) : left === true && type === "dict" ? (
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
          </div>
        ) : left === true && type === "variable" ? (
          <div className="mt-2 w-full">
            <VariablesComponent vid={version?.id} nodeId={data.id} flowId={flowId} onChange={(newValue) => {
              data.node!.template[name].value = newValue;
              handleOnNewValue(newValue);
            }} />
          </div>
        ) : left === true && type === "bisheng_model" ? (
          <div className="mt-2 w-full">
            <ModelSelect
              type='flow'
              value={data.node!.template[name].value || null}
              onChange={(newValue) => {
                data.node!.template[name].value = newValue;
                handleOnNewValue(newValue);
              }}
            />
          </div>
        ) : left === true && type === "bisheng_embedding" ? (
          <div className="mt-2 w-full">
            <ModelSelect
              type='flow'
              modelType="embedding"
              value={data.node!.template[name].value || null}
              onChange={(newValue) => {
                data.node!.template[name].value = newValue;
                handleOnNewValue(newValue);
              }}
            />
          </div>
        ) : (
          <></>
        )}
      </>
    </div>
  );
}
