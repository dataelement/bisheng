import { Copy, Settings2, Trash2 } from "lucide-react";
import { useContext, useState } from "react";
import { useReactFlow } from "reactflow";
import ShadTooltip from "../../../../components/ShadTooltipComponent";
import { TabsContext } from "../../../../contexts/tabsContext";
import EditNodeModal from "../../../../modals/EditNodeModal";
import { classNames } from "../../../../utils";

const NodeToolbarComponent = (props) => {
  const [nodeLength, setNodeLength] = useState(
    Object.keys(props.data.node.template).filter(
      (t) =>
        t.charAt(0) !== "_" &&
        props.data.node.template[t].show &&
        (props.data.node.template[t].type === "str" ||
          props.data.node.template[t].type === "bool" ||
          props.data.node.template[t].type === "float" ||
          props.data.node.template[t].type === "code" ||
          props.data.node.template[t].type === "prompt" ||
          props.data.node.template[t].type === "file" ||
          props.data.node.template[t].type === "Any" ||
          props.data.node.template[t].type === "int")
    ).length
  );

  const { paste } = useContext(TabsContext);
  const reactFlowInstance = useReactFlow();
  return (
    <>
      <div className="w-26 h-10">
        <span className="isolate inline-flex rounded-md shadow-sm">
          <ShadTooltip content="delete" side="top">
            <button
              className="rounded-l-md bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted"
              onClick={() => { props.deleteNode(props.data.id); }}
            >
              <Trash2 className="h-4 w-4"></Trash2>
            </button>
          </ShadTooltip>

          <ShadTooltip content="copy" side="top">
            <button
              className="-ml-px bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted"
              onClick={(event) => {
                event.preventDefault();
                paste(
                  {
                    nodes: [reactFlowInstance.getNode(props.data.id)],
                    edges: [],
                  },
                  {
                    x: 50,
                    y: 10,
                    paneX: reactFlowInstance.getNode(props.data.id).position.x,
                    paneY: reactFlowInstance.getNode(props.data.id).position.y,
                  }
                );
              }}
            >
              <Copy className="h-4 w-4"></Copy>
            </button>
          </ShadTooltip>

          {/* <ShadTooltip
            content={props.data.node.documentation === "" ? "文档正在更新" : "查看文档"}
            side="top"
          >
            <a
              className={classNames(
                "-ml-px bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted" +
                (props.data.node.documentation === "" ? " text-muted-foreground" : " text-foreground")
              )}
              target="_blank"
              rel="noopener noreferrer"
              href={props.data.node.documentation}
              // deactivate link if no documentation is provided
              onClick={(event) => {
                if (props.data.node.documentation === "") {
                  event.preventDefault();
                }
              }}
            >
              <FileText className="h-4 w-4 "></FileText>
            </a>
          </ShadTooltip> */}

          <ShadTooltip content="Edit Node" side="top">
            <button
              className={classNames(
                "rounded-r-md -ml-px bg-background px-2 py-2 shadow-md ring-inset transition-all hover:bg-muted" +
                (nodeLength == 0 ? " text-muted-foreground" : " text-foreground")
              )}
              onClick={(event) => {
                if (nodeLength == 0) { event.preventDefault(); }
                event.preventDefault();
                props.openPopUp(<EditNodeModal data={props.data} />);
              }}
            >
              <Settings2 className="h-4 w-4 "></Settings2>
            </button>
          </ShadTooltip>
        </span>
      </div>
    </>
  );
};

export default NodeToolbarComponent;
