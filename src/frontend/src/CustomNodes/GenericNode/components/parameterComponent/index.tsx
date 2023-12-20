import { Info } from "lucide-react";
import React, { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Handle, Position, useUpdateNodeInternals } from "reactflow";
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
import { MAX_LENGTH_TO_SCROLL_TOOLTIP } from "../../../../constants";
import { PopUpContext } from "../../../../contexts/popUpContext";
import { TabsContext } from "../../../../contexts/tabsContext";
import { typesContext } from "../../../../contexts/typesContext";
import CollectionNameComponent from "../../../../pages/FlowPage/components/CollectionNameComponent";
import { ParameterComponentType } from "../../../../types/components";
import { cleanEdges, convertObjToArray, convertValuesToNumbers, hasDuplicateKeys } from "../../../../util/reactflowUtils";
import {
  classNames,
  getNodeNames,
  getRandomKeyByssmm,
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
  onChange
}: ParameterComponentType) {
  // console.log('data, id :>> ', data.id, id, type);
  const { id: flowId } = useParams();

  const ref = useRef(null);
  const refHtml = useRef(null);
  const refNumberComponents = useRef(0);
  const infoHtml = useRef(null);
  const updateNodeInternals = useUpdateNodeInternals();
  const [position, setPosition] = useState(0);
  const { closePopUp } = useContext(PopUpContext);
  const { setTabsState, tabId, save } = useContext(TabsContext);

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
    // 特殊处理milvus、ElasticKeywordsSearch组件的 disabled
    if (((data.type === "Milvus" && name === 'collection_name') || (data.type === "ElasticKeywordsSearch" && name === 'index_name'))
      && reactFlowInstance?.getEdges().some((e) => e.targetHandle.indexOf('documents') !== -1
        && e.targetHandle.indexOf(data.id) !== -1)) {
      dis = true
    }
    return dis
  }, [id, data, reactFlowInstance])
  // milvus 组件，知识库不为空是 embbeding取消必填限制
  useEffect(() => {
    if (data.type === "Milvus" && data.node.template.embedding) {
      const hidden = disabled ? false : !!data.node.template.collection_name.value
      data.node.template.embedding.required = !hidden
      data.node.template.embedding.show = !hidden
      if (hidden) data.node.template.connection_args.value = ''
      onChange?.()
    }
  }, [data, disabled])
  const handleRemoveMilvusEmbeddingEdge = () => {
    const edges = reactFlowInstance.getEdges().filter(edge => edge.targetHandle.indexOf('Embeddings|embedding|Milvus') === -1)
    reactFlowInstance.setEdges(edges)
  }
  const [myData, setMyData] = useState(useContext(typesContext).data);

  const handleOnNewValue = useCallback((newValue: any) => {
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
  }, [data, tabId]);

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
    const groupedObj = groupByFamily(myData, tooltipTitle, left, data.type);

    refNumberComponents.current = groupedObj[0]?.type?.length;

    refHtml.current = groupedObj.map((item, i) => {
      const Icon: any = nodeIconsLucide[item.family];

      return (
        <span
          key={getRandomKeyByssmm() + item.family + i}
          className={classNames(
            i > 0 ? "mt-2 flex items-center" : "flex items-center"
          )}
        >
          <div
            className="h-5 w-5"
            style={{
              color: nodeColors[item.family],
            }}
          >
            {/* <Icon
              className="h-5 w-5"
              strokeWidth={1.5}
              style={{
                color: nodeColors[item.family] ?? nodeColors.unknown,
              }}
            /> */}
          </div>
          <span className="ps-2 text-xs text-foreground">
            {getNodeNames()[item.family] ?? ""}{" "}
            <span className="text-xs">
              {" "}
              {item.type === "" ? "" : " - "}
              {item.type.split(", ").length > 2
                ? item.type.split(", ").map((el, i) => (
                  <React.Fragment key={el + i}>
                    <span>
                      {i === item.type.split(", ").length - 1
                        ? el
                        : (el += `, `)}
                    </span>
                  </React.Fragment>
                ))
                : item.type}
            </span>
          </span>
        </span>
      );
    });
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
            type === "button") &&
          !optionalHandle ? (
          <></>
        ) : (
          <ShadTooltip
            styleClasses={
              refNumberComponents.current > MAX_LENGTH_TO_SCROLL_TOOLTIP
                ? "tooltip-fixed-width custom-scroll overflow-y-scroll nowheel"
                : "tooltip-fixed-width"
            }
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
        {left === true &&
          type === "str" &&
          !data.node.template[name].options ? (
          <div className="mt-2 w-full">
            {data.node.template[name].list ? (
              // input list
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
              // 多行数如
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
                onSelect={(val, id) => { handleOnNewLibValue(val, id); val && handleRemoveMilvusEmbeddingEdge() }}
                onChange={() => { }}
              />
            ) : (
              // 单行输入
              <InputComponent
                disabled={disabled}
                disableCopyPaste={true}
                password={data.node.template[name].password ?? false}
                value={data.node.template[name].value ?? ""}
                onChange={handleOnNewValue}
              />
            )}
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
              disableCopyPaste={true}
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
                data.node = nodeClass;
              }}
              nodeClass={data.node}
              disabled={disabled}
              value={data.node.template[name].value ?? ""}
              onChange={handleOnNewValue}
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
                save();
              }}
            ></InputFileComponent>
          </div>
        ) : left === true && type === "int" ? (
          <div className="mt-2 w-full">
            <IntComponent
              disabled={disabled}
              disableCopyPaste={true}
              value={data.node.template[name].value ?? ""}
              onChange={handleOnNewValue}
            />
          </div>
        ) : left === true && type === "prompt" ? (
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
            <VariablesComponent nodeId={data.id} flowId={flowId} onChange={(newValue) => {
              data.node!.template[name].value = newValue;
              handleOnNewValue(newValue);
            }} />
          </div>
        ) : (
          <></>
        )}
      </>
    </div>
  );
}
