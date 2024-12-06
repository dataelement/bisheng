import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select-custom";
import { alertContext } from "@/contexts/alertContext";
import { TabsContext } from "@/contexts/tabsContext";
import { typesContext } from "@/contexts/typesContext";
import { undoRedoContext } from "@/contexts/undoRedoContext";
import { userContext } from "@/contexts/userContext";
import EditNodeModal from "@/modals/EditNodeModal";
import { downloadNode, expandGroupNode, removeApiKeys, updateFlowPosition } from "@/util/reactflowUtils";
import { classNames } from "@/utils";
import cloneDeep from "lodash-es/cloneDeep";
import { AlarmClock, Combine, Copy, Download, MoreHorizontal, SaveAll, Settings2, Trash2 } from "lucide-react";
import { useContext, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useReactFlow } from "@xyflow/react";
// 组件头部按钮组
const NodeToolbarComponent = ({ data, deleteNode, openPopUp, position }) => {
  const [nodeLength, setNodeLength] = useState(
    Object.keys(data.node.template).filter(
      (t) =>
        t.charAt(0) !== "_" &&
        data.node.template[t].show &&
        (data.node.template[t].type === "str" ||
          data.node.template[t].type === "bool" ||
          data.node.template[t].type === "float" ||
          data.node.template[t].type === "code" ||
          data.node.template[t].type === "prompt" ||
          data.node.template[t].type === "file" ||
          data.node.template[t].type === "Any" ||
          data.node.template[t].type === "int")
    ).length
  );

  const { version, paste } = useContext(TabsContext);
  const reactFlowInstance = useReactFlow();
  const isGroup = !!data.node?.flow;

  const { takeSnapshot } = useContext(undoRedoContext);

  const { setSuccessData } = useContext(alertContext);
  const saveComponentSuccess = () => {
    setSuccessData({
      title: "已保存到本地组件/Saved",
    });
  }

  const { types } = useContext(typesContext);
  const hasVersion = useMemo(() => {
    // 部分组件开放“历史/history”入口：agent、chains、retrievers 、vector store 4类组件。
    return ["chains", "agents", "vectorstores", "retrievers"].includes(types[data.type])
  }, [data, types])

  const navigate = useNavigate()
  const { id: flowId } = useParams()
  const { addSavedComponent, checkComponentsName } = useContext(userContext)
  const handleSelectChange = (event) => {
    switch (event) {
      case "advanced":
        // setShowModalAdvanced(true);
        openPopUp(<EditNodeModal data={data} />);
        break;
      case "show":
        // takeSnapshot();
        // setShowNode(data.showNode ?? true ? false : true);
        break;
      case "saveCom":
        if (checkComponentsName(data.node.display_name)) {
          bsConfirm({
            title: '组件已存在',
            desc: `组件 ${data.node.display_name} 已存在，覆盖原有组件还是继续创新建组件？`,
            showClose: true,
            okTxt: '覆盖',
            canelTxt: '创建新组建',
            onOk(next) {
              addSavedComponent(cloneDeep(data), true).then(saveComponentSuccess)
              next()
            },
            onCancel() {
              addSavedComponent(cloneDeep(data), false).then(saveComponentSuccess)
            }
          })
        } else {
          addSavedComponent(cloneDeep(data), false, false).then(saveComponentSuccess)
        }
        break;
      case "documentation":
        // if (data.node?.documentation) openInNewTab(data.node?.documentation);
        break;
      case "disabled":
        break;
      case "version":
        navigate(`/diff/${flowId}/${version.id}/${data.id}`)
        break;
      case "export":
        const cleanFlow = removeApiKeys({ data: { nodes: [{ data }] } } as any)
        downloadNode(cleanFlow.data.nodes[0].data);
        break;
      case "ungroup":
        takeSnapshot();
        expandGroupNode(
          data.id,
          updateFlowPosition(position, data.node?.flow!),
          data.node!.template,
          reactFlowInstance.getNodes(),
          reactFlowInstance.getEdges(),
          reactFlowInstance.setNodes,
          reactFlowInstance.setEdges
        );
        break;
    }
  };

  return (
    <>
      <div className="w-26 h-10">
        <span className="isolate inline-flex rounded-md shadow-sm">
          {/* 删除 */}
          <ShadTooltip content="delete" side="top">
            <button
              className="rounded-l-md bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted"
              onClick={() => { deleteNode(data.id); }}
            >
              <Trash2 className="h-4 w-4"></Trash2>
            </button>
          </ShadTooltip>
          {/* 复制 */}
          <ShadTooltip content="copy" side="top">
            <button
              className="-ml-px bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted"
              onClick={(event) => {
                event.preventDefault();
                paste(
                  {
                    nodes: [reactFlowInstance.getNode(data.id)],
                    edges: [],
                  },
                  {
                    x: 50,
                    y: 10,
                    paneX: reactFlowInstance.getNode(data.id).position.x,
                    paneY: reactFlowInstance.getNode(data.id).position.y,
                  }
                );
              }}
            >
              <Copy className="h-4 w-4"></Copy>
            </button>
          </ShadTooltip>
          {/* 版本 */}
          {
            hasVersion && !isGroup && <ShadTooltip content="version" side="top">
              <button
                className="-ml-px bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted"
                onClick={() => handleSelectChange('version')}
              >
                <AlarmClock className="h-4 w-4"></AlarmClock>
              </button>
            </ShadTooltip>
          }
          {/* 编辑 */}
          {
            nodeLength > 0 && <ShadTooltip content="edit" side="top">
              <button
                className="-ml-px bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted"
                onClick={() => handleSelectChange('advanced')}
              >
                <Settings2 className="h-4 w-4"></Settings2>
              </button>
            </ShadTooltip>
          }
          {/* more */}
          <Select onValueChange={handleSelectChange} value="">
            <ShadTooltip content="More" side="top">
              <SelectTrigger className={'xxx'}>
                <div>
                  <div
                    data-testid="more-options-modal"
                    className={classNames(
                      "rounded-r-md -ml-px bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted" +
                      (nodeLength == 0 ? " text-muted-foreground" : " text-foreground")
                    )}
                  >
                    <MoreHorizontal
                      name="MoreHorizontal"
                      className="h-4 w-4"
                    />
                  </div>
                </div>
              </SelectTrigger>
            </ShadTooltip>
            <SelectContent>
              <SelectItem value={"export"}>
                <div className="flex" data-testid="save-button-modal">
                  <Download className="relative top-0.5 mr-2 h-4 w-4" />
                  {" "}export{" "}
                </div>{" "}
              </SelectItem>
              <SelectItem value={"saveCom"}>
                <div className="flex" data-testid="save-button-modal">
                  <SaveAll className="relative top-0.5 mr-2 h-4 w-4" />
                  {" "}Save{" "}
                </div>{" "}
              </SelectItem>
              {isGroup && (
                <SelectItem value="ungroup">
                  <div className="flex">
                    <Combine
                      name="Combine"
                      className="relative top-0.5 mr-2 h-4 w-4"
                    />{" "}
                    Ungroup{" "}
                  </div>
                </SelectItem>
              )}
            </SelectContent>
          </Select>
        </span>
      </div>
    </>
  );
};

export default NodeToolbarComponent;
