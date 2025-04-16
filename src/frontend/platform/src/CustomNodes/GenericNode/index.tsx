import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import NodeToolbarComponent from "@/pages/BuildPage/skills/editSkill/nodeToolbarComponent";
import { Zap } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { NodeToolbar } from "@xyflow/react";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Button } from "../../components/bs-ui/button";
import EditLabel from "../../components/ui/editLabel";
import { useSSE } from "../../contexts/SSEContext";
import { alertContext } from "../../contexts/alertContext";
import { PopUpContext } from "../../contexts/popUpContext";
import { typesContext } from "../../contexts/typesContext";
import { NodeDataType } from "../../types/flow";
import {
  classNames,
  nodeColors,
  nodeIconsLucide,
  toTitleCase,
} from "../../utils";
import ParameterComponent from "./components/parameterComponent";

export default function GenericNode({ data, positionAbsoluteX, positionAbsoluteY, selected }: {
  data: NodeDataType;
  positionAbsoluteX: number;
  positionAbsoluteY: number;
  selected: boolean;
}) {
  const { id: flowId } = useParams();
  // console.log('data :>> ', data);

  const { setErrorData } = useContext(alertContext);
  const showError = useRef(true);
  const { types, deleteNode } = useContext(typesContext);

  const { closePopUp, openPopUp } = useContext(PopUpContext);
  // any to avoid type conflict
  const Icon: any =
    nodeIconsLucide[data.type] || nodeIconsLucide[types[data.type]];
  const [validationStatus, setValidationStatus] = useState(null);
  // State for outline color
  const { sseData, isBuilding } = useSSE();

  // useEffect(() => {
  //   if (reactFlowInstance) {
  //     setParams(Object.values(reactFlowInstance.toObject()));
  //   }
  // }, [save]);

  // New useEffect to watch for changes in sseData and update validation status
  useEffect(() => {
    const relevantData = sseData[data.id];
    if (relevantData) {
      // Extract validation information from relevantData and update the validationStatus state
      setValidationStatus(relevantData);
    } else {
      setValidationStatus(null);
    }
  }, [sseData, data.id]);

  if (!Icon) {
    if (showError.current) {
      setErrorData({
        title: data.type
          ? `can be translated to "Unable to render the ${data.type} node. Please check your JSON file.`
          : `can be translated to "One node cannot be rendered. Please check your JSON file.`
      });
      showError.current = false;
    }
    deleteNode(data.id);
    return;
  }

  const [_, fouceUpdateNode] = useState(false)
  const isGroup = !!data.node?.flow;

  return (
    <>
      <NodeToolbar>
        <NodeToolbarComponent
          position={{ x: positionAbsoluteX, y: positionAbsoluteY }}
          data={data}
          openPopUp={openPopUp}
          deleteNode={deleteNode}
        ></NodeToolbarComponent>
      </NodeToolbar>

      <div className={classNames("border-4 generic-node-div relative", selected ? "border-ring" : "")} style={{ borderColor: nodeColors[types[data.type]] ?? nodeColors.unknown }}>
        {isGroup && <div className={`generic-node-div absolute border-2 w-full h-full left-3 top-3 z-[-1] ${selected ? "border-ring" : ""}`} style={{ borderColor: nodeColors[types[data.type]] ?? nodeColors.unknown }}>
          <div className={`generic-node-div absolute border-4 w-full h-full left-3 top-3 z-[-1] bg-transparent ${selected ? "border-ring" : ""}`} style={{ borderColor: nodeColors[types[data.type]] ?? nodeColors.unknown }}>
          </div>
        </div>}
        <div className="generic-node-div-title">
          {/* title */}
          <div className="generic-node-title-arrangement">
            {/* <Icon
              strokeWidth={1.5}
              className="generic-node-icon"
              style={{
                color: nodeColors[types[data.type]] ?? nodeColors.unknown,
              }}
            /> */}
            <div className="round-button-div">
              <div>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="generic-node-status-position">
                        <div
                          className={classNames(
                            validationStatus && validationStatus.valid ? "green-status" : "status-build-animation", "status-div"
                          )}
                        ></div>
                        <div
                          className={classNames(
                            validationStatus && !validationStatus.valid ? "red-status" : "status-build-animation", "status-div"
                          )}
                        ></div>
                        <div
                          className={classNames(
                            !validationStatus || isBuilding ? "yellow-status" : "status-build-animation", "status-div"
                          )}
                        ></div>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent className="bg-background text-foreground">
                      {
                        isBuilding ? (<span>build...</span>) :
                          !validationStatus ? (
                            <span className="flex">
                              Build{" "} <Zap className="mx-0.5 h-5 fill-build-trigger stroke-build-trigger stroke-1" strokeWidth={1.5} />{" "} flow to validate status.
                            </span>
                          ) : (
                            <div className="max-h-96 overflow-auto">
                              {validationStatus.params ? validationStatus.params.split("\n")
                                .map((line, index) => <div key={index}>{line}</div>)
                                : ""}
                            </div>
                          )
                      }
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
            <div className="generic-node-tooltip-div">
              <ShadTooltip content={data.node.display_name}>
                <div className="generic-node-tooltip-div ">
                  {isGroup ? <EditLabel
                    rule={[
                      { required: true }
                    ]}
                    str={data.node.display_name}
                    onChange={(val) => { (data.node.display_name = val); fouceUpdateNode(!_) }}>
                    {(val) => <div className="max-w-[300px] overflow-hidden text-ellipsis">{val}</div>}
                  </EditLabel> : data.node.display_name}
                </div>
              </ShadTooltip>
            </div>
          </div>
          {/* <div className="round-button-div">
            <button className="relative" onClick={(event) => { event.preventDefault(); openPopUp(<NodeModal data={data} />)}} ></button>
          </div> */}
        </div >

        <div className="generic-node-desc nodrag">
          <div className="generic-node-desc-text">{data.node.description}</div>
          <>
            {Object.keys(data.node.template)
              .filter((t) => t.charAt(0) !== "_")
              .map((t: string, idx) => (
                <div key={idx}>
                  {/* {idx === 0 ? (
                                <div
                                    className={classNames(
                                        "px-5 py-2 mt-2 text-center",
                                        Object.keys(data.node.template).filter(
                                            (key) =>
                                                !key.startsWith("_") &&
                                                data.node.template[key].show &&
                                                !data.node.template[key].advanced
                                        ).length === 0
                                            ? "hidden"
                                            : ""
                                    )}
                                >
                                    Inputs
                                </div>
                            ) : (
                                <></>
                            )} */}
                  {data.node.template[t].show &&
                    !data.node.template[t].advanced ? (
                    <ParameterComponent
                      data={data}
                      isGroup={isGroup}
                      color={
                        nodeColors[types[data.node.template[t].type]] ??
                        nodeColors[data.node.template[t].type] ??
                        nodeColors.unknown
                      }
                      title={
                        data.node.template[t].display_name
                          ? data.node.template[t].display_name
                          : data.node.template[t].name
                            ? toTitleCase(data.node.template[t].name)
                            : toTitleCase(t)
                      }
                      info={data.node.template[t].info}
                      name={t}
                      tooltipTitle={
                        data.node.template[t].input_types?.join("\n") ??
                        data.node.template[t].type
                      }
                      required={data.node.template[t].required}
                      id={(data.node.template[t].input_types?.join(";") ?? data.node.template[t].type) + "|" + t + "|" + data.id}
                      left={true}
                      type={data.node.template[t].type}
                      optionalHandle={data.node.template[t].input_types}
                      onChange={() => fouceUpdateNode(!_)}
                    />
                  ) : (
                    <></>
                  )}
                </div>
              ))}
            <div
              className={classNames(
                Object.keys(data.node.template).length < 1 ? "hidden" : "",
                "flex-max-width justify-center"
              )}
            >
              {" "}
            </div>
            {/* 输出节点 */}
            <ParameterComponent
              data={data}
              color={nodeColors[types[data.type]] ?? nodeColors.unknown}
              title={
                data.node.output_types && data.node.output_types.length > 0
                  ? data.node.output_types.join("|")
                  : data.type
              }
              tooltipTitle={data.node.base_classes.join("\n")}
              id={[data.type, data.id, ...data.node.base_classes].join("|")}
              type={data.node.base_classes.join("|")}
              left={false}
            />
            {data.type === 'Report' && <div className="w-full bg-muted px-5 py-2">
              <Link to={`/report/${flowId}`}><Button variant="outline" className="px-10" onClick={() => {
                const dom = document.getElementById("flow-page") as HTMLElement;
                if (dom) dom.className += ' report-hidden';
              }}>Edit</Button></Link>
            </div>}
          </>
        </div>
      </div >
    </>
  );
}
