import { cloneDeep } from "lodash-es";
import {
  Connection,
  Edge,
  Node,
  OnSelectionChangeParams,
  ReactFlowJsonObject,
  XYPosition,
} from "reactflow";

// import { downloadFlowsFromDatabase } from "../controllers/API";
import {
  APIKindType,
  APIObjectType,
  APITemplateType,
  TemplateVariableType
} from "../types/api";
import {
  FlowType,
  NodeDataType,
  NodeType,
  sourceHandleType,
  targetHandleType,
} from "../types/flow";
import {
  findLastNodeType,
  generateFlowType,
  unselectAllNodesType,
  updateEdgesHandleIdsType,
} from "../types/utils/reactflowUtils";
import { generateUUID } from "../utils";
import {
  getFieldTitle,
  toTitleCase
} from "./utils";

export const LANGFLOW_SUPPORTED_TYPES = new Set([
  "str",
  "bool",
  "float",
  "code",
  "prompt",
  "file",
  "int",
  "dict",
  "NestedDict",
  "bisheng_model",
  "bisheng_embedding"
]);

// edges (线)文档
export function cleanEdges(nodes: Node[], edges: Edge[]) {
  let newEdges = cloneDeep(edges);
  edges.forEach((edge) => {
    // check if the source and target node still exists
    const sourceNode = nodes.find((node) => node.id === edge.source);
    const targetNode = nodes.find((node) => node.id === edge.target);
    if (!sourceNode || !targetNode) {
      newEdges = newEdges.filter((edg) => edg.id !== edge.id);
      return;
    }
    // check if the source and target handle still exists
    const sourceHandle = edge.sourceHandle; //right
    const targetHandle = edge.targetHandle; //left
    if (targetHandle) {
      const field = targetHandle.split('|')[1]
      const targetNodeTargetHandle =
        targetNode.data.node!.template[field]?.type + '|' +
        field + '|' +
        targetNode.data.id

      // if (targetNode.data.node!.template[field]?.proxy) {
      //   id.proxy = targetNode.data.node!.template[field]?.proxy;
      // }
      if (targetNodeTargetHandle !== targetHandle) {
        newEdges = newEdges.filter((e) => e.id !== edge.id);
      }
    }
    if (sourceHandle) {
      const sourceNodeSourceHandle =
        sourceNode.data.type + '|' +
        sourceNode.data.id + '|' +
        sourceNode.data.node!.base_classes.join('|')

      if (sourceNodeSourceHandle !== sourceHandle) {
        newEdges = newEdges.filter((e) => e.id !== edge.id);
      }
    }
  });
  return newEdges;
}

export function unselectAllNodes({ updateNodes, data }: unselectAllNodesType) {
  let newNodes = cloneDeep(data);
  newNodes.forEach((node: Node) => {
    node.selected = false;
  });
  updateNodes(newNodes!);
}

// utils中的新方法
export function isValidConnection(
  { source, target, sourceHandle, targetHandle }: Connection,
  nodes: Node[],
  edges: Edge[]
) {
  const targetHandleObject: targetHandleType = scapeJSONParse(targetHandle!);
  const sourceHandleObject: sourceHandleType = scapeJSONParse(sourceHandle!);
  if (
    targetHandleObject.inputTypes?.some(
      (n) => n === sourceHandleObject.dataType
    ) ||
    sourceHandleObject.baseClasses.some(
      (t) =>
        targetHandleObject.inputTypes?.some((n) => n === t) ||
        t === targetHandleObject.type
    )
  ) {
    let targetNode = nodes.find((node) => node.id === target!)?.data?.node;
    if (!targetNode) {
      if (!edges.find((e) => e.targetHandle === targetHandle)) {
        return true;
      }
    } else if (
      (!targetNode.template[targetHandleObject.fieldName].list &&
        !edges.find((e) => e.targetHandle === targetHandle)) ||
      targetNode.template[targetHandleObject.fieldName].list
    ) {
      return true;
    }
  }
  return false;
}

export function removeApiKeys(flow: FlowType): FlowType {
  let cleanFLow = cloneDeep(flow);
  cleanFLow.data!.nodes.forEach((node) => {
    for (const key in node.data.node.template) {
      if (node.data.node.template[key].password) {
        node.data.node.template[key].value = "";
      }
    }
  });
  return cleanFLow;
}

export function updateTemplate(
  reference: APITemplateType,
  objectToUpdate: APITemplateType
): APITemplateType {
  let clonedObject: APITemplateType = cloneDeep(reference);

  // Loop through each key in the reference object
  for (const key in clonedObject) {
    // If the key is not in the object to update, add it
    if (objectToUpdate[key] && objectToUpdate[key].value) {
      clonedObject[key].value = objectToUpdate[key].value;
    }
    if (
      objectToUpdate[key] &&
      objectToUpdate[key].advanced !== null &&
      objectToUpdate[key].advanced !== undefined
    ) {
      clonedObject[key].advanced = objectToUpdate[key].advanced;
    }
  }
  return clonedObject;
}

export const processDataFromFlow = (flow: FlowType, refreshIds = true) => {
  let data = flow?.data ? flow.data : null;
  if (data) {
    processFlowEdges(flow);
    //prevent node update for now
    // processFlowNodes(flow);
    //add animation to text type edges
    updateEdges(data.edges);
    // updateNodes(data.nodes, data.edges);
    if (refreshIds) updateIds(data); // Assuming updateIds is defined elsewhere
  }
  return data;
};
// utils中的新方法
export function updateIds(newFlow: ReactFlowJsonObject) {
  let idsMap = {};

  if (newFlow.nodes)
    newFlow.nodes.forEach((node: NodeType) => {
      // Generate a unique node ID
      let newId = getNodeId(
        node.data.node?.flow ? "GroupNode" : node.data.type
      );
      idsMap[node.id] = newId;
      node.id = newId;
      node.data.id = newId;
      // Add the new node to the list of nodes in state
    });

  if (newFlow.edges)
    newFlow.edges.forEach((edge: Edge) => {
      edge.source = idsMap[edge.source];
      edge.target = idsMap[edge.target];
      const sourceHandleObject: sourceHandleType = scapeJSONParse(
        edge.sourceHandle!
      );
      edge.sourceHandle = scapedJSONStringfy({
        ...sourceHandleObject,
        id: edge.source,
      });
      if (edge.data?.sourceHandle?.id) {
        edge.data.sourceHandle.id = edge.source;
      }
      const targetHandleObject: targetHandleType = scapeJSONParse(
        edge.targetHandle!
      );
      edge.targetHandle = scapedJSONStringfy({
        ...targetHandleObject,
        id: edge.target,
      });
      if (edge.data?.targetHandle?.id) {
        edge.data.targetHandle.id = edge.target;
      }
      edge.id =
        "reactflow__edge-" +
        edge.source +
        edge.sourceHandle +
        "-" +
        edge.target +
        edge.targetHandle;
    });
  return idsMap;
}

export function buildTweaks(flow: FlowType) {
  return flow.data!.nodes.reduce((acc, node) => {
    acc[node.data.id] = {};
    return acc;
  }, {});
}

export function validateNode(node: NodeType, edges: Edge[]): Array<string> {
  if (!node.data?.node?.template || !Object.keys(node.data.node.template)) {
    return [
      "We've noticed a potential issue with a node in the flow. Please review it and, if necessary, submit a bug report with your exported flow file. Thank you for your help!",
    ];
  }

  const {
    type,
    node: { template },
  } = node.data;

  return Object.keys(template).reduce((errors: Array<string>, t) => {
    if (
      template[t].required &&
      template[t].show &&
      (template[t].value === undefined ||
        template[t].value === null ||
        template[t].value === "") &&
      !edges.some(
        (edge) =>
          (scapeJSONParse(edge.targetHandle!) as targetHandleType).fieldName ===
          t &&
          (scapeJSONParse(edge.targetHandle!) as targetHandleType).id ===
          node.id
      )
    ) {
      errors.push(`${type} is missing ${getFieldTitle(template, t)}.`);
    } else if (
      template[t].type === "dict" &&
      template[t].required &&
      template[t].show &&
      (template[t].value !== undefined ||
        template[t].value !== null ||
        template[t].value !== "")
    ) {
      if (hasDuplicateKeys(template[t].value))
        errors.push(
          `${type} (${getFieldTitle(
            template,
            t
          )}) contains duplicate keys with the same values.`
        );
      if (hasEmptyKey(template[t].value))
        errors.push(
          `${type} (${getFieldTitle(template, t)}) field must not be empty.`
        );
    }
    return errors;
  }, [] as string[]);
}

export function validateNodes(nodes: Node[], edges: Edge[]) {
  if (nodes.length === 0) {
    return [
      "No nodes found in the flow. Please add at least one node to the flow.",
    ];
  }
  return nodes.flatMap((n: NodeType) => validateNode(n, edges));
}

export function updateEdges(edges: Edge[]) {
  if (edges)
    edges.forEach((edge) => {
      const targetHandleObject: targetHandleType = scapeJSONParse(
        edge.targetHandle!
      );
      edge.className =
        (targetHandleObject.type === "Text"
          ? "stroke-gray-800 "
          : "stroke-gray-900 ") + " stroke-connection";
      edge.animated = targetHandleObject.type === "Text";
    });
}

export function addVersionToDuplicates(flow: FlowType, flows: FlowType[]) {
  const existingNames = flows.map((item) => item.name);
  let newName = flow.name;
  let count = 1;

  while (existingNames.includes(newName)) {
    newName = `${flow.name} (${count})`;
    count++;
  }

  return newName;
}

export function updateEdgesHandleIds({
  edges,
  nodes,
}: updateEdgesHandleIdsType): Edge[] {
  let newEdges = cloneDeep(edges);
  newEdges.forEach((edge) => {
    const sourceNodeId = edge.source;
    const targetNodeId = edge.target;
    const sourceNode = nodes.find((node) => node.id === sourceNodeId);
    const targetNode = nodes.find((node) => node.id === targetNodeId);
    let source = edge.sourceHandle;
    let target = edge.targetHandle;
    //right
    let newSource: sourceHandleType;
    //left
    let newTarget: targetHandleType;
    if (target && targetNode) {
      let field = target.split("|")[1];
      newTarget = {
        type: targetNode.data.node!.template[field].type,
        fieldName: field,
        id: targetNode.data.id,
        inputTypes: targetNode.data.node!.template[field].input_types,
      };
    }
    if (source && sourceNode) {
      newSource = {
        id: sourceNode.data.id,
        baseClasses: sourceNode.data.node!.base_classes,
        dataType: sourceNode.data.type,
      };
    }
    edge.sourceHandle = scapedJSONStringfy(newSource!);
    edge.targetHandle = scapedJSONStringfy(newTarget!);
    const newData = {
      sourceHandle: scapeJSONParse(edge.sourceHandle),
      targetHandle: scapeJSONParse(edge.targetHandle),
    };
    edge.data = newData;
  });
  return newEdges;
}

export function handleKeyDown(
  e:
    | React.KeyboardEvent<HTMLInputElement>
    | React.KeyboardEvent<HTMLTextAreaElement>,
  inputValue: string | string[] | null,
  block: string
) {
  //condition to fix bug control+backspace on Windows/Linux
  if (
    (typeof inputValue === "string" &&
      (e.metaKey === true || e.ctrlKey === true) &&
      e.key === "Backspace" &&
      (inputValue === block ||
        inputValue?.charAt(inputValue?.length - 1) === " " ||
        /[!@#$%^&*()\-_=+[\]{}|;:'",.<>/?\\`´]/.test(inputValue?.charAt(inputValue?.length - 1)))) ||
    (navigator.userAgent.toUpperCase().includes("MAC") &&
      e.ctrlKey === true &&
      e.key === "Backspace")
  ) {
    e.preventDefault();
    e.stopPropagation();
  }

  if (e.ctrlKey === true && e.key === "Backspace" && inputValue === block) {
    e.preventDefault();
    e.stopPropagation();
  }
}

export function handleOnlyIntegerInput(
  event: React.KeyboardEvent<HTMLInputElement>
) {
  if (
    event.key === "." ||
    event.key === "-" ||
    event.key === "," ||
    event.key === "e" ||
    event.key === "E" ||
    event.key === "+"
  ) {
    event.preventDefault();
  }
}

export function getConnectedNodes(
  edge: Edge,
  nodes: Array<NodeType>
): Array<NodeType> {
  const sourceId = edge.source;
  const targetId = edge.target;
  return nodes.filter((node) => node.id === targetId || node.id === sourceId);
}

export function convertObjToArray(singleObject: object | string) {
  if (typeof singleObject === "string") {
    singleObject = JSON.parse(singleObject);
  }
  if (Array.isArray(singleObject)) return singleObject;

  let arrConverted: any[] = [];
  if (typeof singleObject === "object") {
    for (const key in singleObject) {
      if (Object.prototype.hasOwnProperty.call(singleObject, key)) {
        const newObj = {};
        newObj[key] = singleObject[key];
        arrConverted.push(newObj);
      }
    }
  }
  return arrConverted;
}

export function convertArrayToObj(arrayOfObjects) {
  if (!Array.isArray(arrayOfObjects)) return arrayOfObjects;

  let objConverted = {};
  for (const obj of arrayOfObjects) {
    for (const key in obj) {
      if (obj.hasOwnProperty(key)) {
        objConverted[key] = obj[key];
      }
    }
  }
  return objConverted;
}

export function hasDuplicateKeys(array) {
  const keys = {};
  // Transforms an empty object into an object array without opening the 'editNode' modal to prevent the flow build from breaking.
  if (!Array.isArray(array)) array = [{ "": "" }];
  for (const obj of array) {
    for (const key in obj) {
      if (keys[key]) {
        return true;
      }
      keys[key] = true;
    }
  }
  return false;
}

export function hasEmptyKey(objArray) {
  // Transforms an empty object into an array without opening the 'editNode' modal to prevent the flow build from breaking.
  if (!Array.isArray(objArray)) objArray = [];
  for (const obj of objArray) {
    for (const key in obj) {
      if (obj.hasOwnProperty(key) && key === "") {
        return true; // Found an empty key
      }
    }
  }
  return false; // No empty keys found
}

export function convertValuesToNumbers(arr) {
  return arr.map((obj) => {
    const newObj = {};
    for (const key in obj) {
      if (obj.hasOwnProperty(key)) {
        let value = obj[key];
        if (/^\d+$/.test(value)) {
          value = value?.toString().trim();
        }
        newObj[key] =
          value === "" || isNaN(value) ? value.toString() : Number(value);
      }
    }
    return newObj;
  });
}

export function scapedJSONStringfy(json: object): string {
  return customStringify(json).replace(/"/g, "œ");
}
export function scapeJSONParse(json: string): any {
  let parsed = json.replace(/œ/g, '"');
  return JSON.parse(parsed);
}

// this function receives an array of edges and return true if any of the handles are not a json string
// 数据结构转新版本
export function checkOldEdgesHandles(edges: Edge[]): boolean {
  return edges.some(
    (edge) =>
      !edge.sourceHandle ||
      !edge.targetHandle ||
      !edge.sourceHandle.includes("{") ||
      !edge.targetHandle.includes("{")
  );
}

export function customStringify(obj: any): string {
  if (typeof obj === "undefined") {
    return "null";
  }

  if (obj === null || typeof obj !== "object") {
    if (obj instanceof Date) {
      return `"${obj.toISOString()}"`;
    }
    return JSON.stringify(obj);
  }

  if (Array.isArray(obj)) {
    const arrayItems = obj.map((item) => customStringify(item)).join(",");
    return `[${arrayItems}]`;
  }

  const keys = Object.keys(obj).sort();
  const keyValuePairs = keys.map(
    (key) => `"${key}":${customStringify(obj[key])}`
  );
  return `{${keyValuePairs.join(",")}}`;
}

export function getMiddlePoint(nodes: Node[]) {
  let middlePointX = 0;
  let middlePointY = 0;

  nodes.forEach((node) => {
    middlePointX += node.position.x;
    middlePointY += node.position.y;
  });

  const totalNodes = nodes.length;
  const averageX = middlePointX / totalNodes;
  const averageY = middlePointY / totalNodes;

  return { x: averageX, y: averageY };
}

export function getNodeId(nodeType: string) {
  return nodeType + "-" + generateUUID(5);
}

export function getHandleId(
  source: string,
  sourceHandle: string,
  target: string,
  targetHandle: string
) {
  return (
    "reactflow__edge-" + source + sourceHandle + "-" + target + targetHandle
  );
}

export function generateFlow(
  selection: OnSelectionChangeParams,
  nodes: Node[],
  edges: Edge[],
  name: string
): generateFlowType {
  const newFlowData = { nodes, edges, viewport: { zoom: 1, x: 0, y: 0 } };
  /*	remove edges that are not connected to selected nodes on both ends
   */
  newFlowData.edges = selection.edges.filter(
    (edge) =>
      selection.nodes.some((node) => node.id === edge.target) &&
      selection.nodes.some((node) => node.id === edge.source)
  );
  newFlowData.nodes = selection.nodes;

  const newFlow: FlowType = {
    data: newFlowData,
    is_component: false,
    name: name,
    description: "",
    //generating local id instead of using the id from the server, can change in the future
    id: generateUUID(5),
    status: 0,
    write: false,
    guide_word: ""
  };
  // filter edges that are not connected to selected nodes on both ends
  // using O(n²) aproach because the number of edges is small
  // in the future we can use a better aproach using a set
  return {
    newFlow,
    removedEdges: edges.filter(
      (edge) =>
        (selection.nodes.some((node) => node.id === edge.target) ||
          selection.nodes.some((node) => node.id === edge.source)) &&
        newFlowData.edges.every((e) => e.id !== edge.id)
    ),
  };
}

export function reconnectEdges(groupNode: NodeType, excludedEdges: Edge[]) {
  let newEdges = cloneDeep(excludedEdges);
  if (!groupNode.data.node!.flow) return [];
  const { nodes, edges } = groupNode.data.node!.flow!.data!;
  const lastNode = findLastNode(groupNode.data.node!.flow!.data!);
  newEdges.forEach((edge) => {
    // 选中的 node 有链接其他 node
    if (lastNode && edge.source === lastNode.id) {
      edge.source = groupNode.id;
      const sourceHandleArr = edge.sourceHandle.split('|')
      sourceHandleArr[1] = groupNode.id
      edge.sourceHandle = sourceHandleArr.join('|');
      // edge.data.sourceHandle = newSourceHandle;
    }
    // 选中的 node 有被链接的 node
    if (nodes.some((node) => node.id === edge.target)) {
      const targetNode = nodes.find((node) => node.id === edge.target)!;
      const targetHandleArr = edge.targetHandle.split('|')
      targetHandleArr[targetHandleArr.length - 1] = groupNode.id;
      targetHandleArr[1] = targetHandleArr[1] + "_" + targetNode.id;
      // const proxy = { id: targetNode.id, field: targetHandle.fieldName };
      // newTargetHandle.proxy = proxy;
      edge.target = groupNode.id;
      edge.targetHandle = targetHandleArr.join('|');
      // edge.data.targetHandle = newTargetHandle;
    }
  });
  return newEdges;
}

export function filterFlow(
  selection: OnSelectionChangeParams,
  setNodes: (update: Node[] | ((oldState: Node[]) => Node[])) => void,
  setEdges: (update: Edge[] | ((oldState: Edge[]) => Edge[])) => void
) {
  setNodes((nodes) => nodes.filter((node) => !selection.nodes.includes(node)));
  setEdges((edges) => edges.filter((edge) => !selection.edges.includes(edge)));
}

export function findLastNode({ nodes, edges }: findLastNodeType) {
  /*
    this function receives a flow and return the last node
  */
  let lastNode = nodes.find((n) => !edges.some((e) => e.source === n.id));
  return lastNode;
}

export function updateFlowPosition(NewPosition: XYPosition, flow: FlowType) {
  const middlePoint = getMiddlePoint(flow.data!.nodes);
  let deltaPosition = {
    x: NewPosition.x - middlePoint.x,
    y: NewPosition.y - middlePoint.y,
  };
  return {
    ...flow,
    data: {
      ...flow.data!,
      nodes: flow.data!.nodes.map((node) => ({
        ...node,
        position: {
          x: node.position.x + deltaPosition.x,
          y: node.position.y + deltaPosition.y,
        },
      })),
    },
  };
}

export function concatFlows(
  flow: FlowType,
  setNodes: (update: Node[] | ((oldState: Node[]) => Node[])) => void,
  setEdges: (update: Edge[] | ((oldState: Edge[]) => Edge[])) => void
) {
  const { nodes, edges } = flow.data!;
  setNodes((old) => [...old, ...nodes]);
  setEdges((old) => [...old, ...edges]);
}

export function validateSelection(
  selection: OnSelectionChangeParams,
  edges: Edge[]
): Array<string> {
  //add edges to selection if selection mode selected only nodes
  if (selection.edges.length === 0) {
    selection.edges = edges;
  }
  // get only edges that are connected to the nodes in the selection
  // first creates a set of all the nodes ids
  let nodesSet = new Set(selection.nodes.map((n) => n.id));
  // then filter the edges that are connected to the nodes in the set
  let connectedEdges = selection.edges.filter(
    (e) => nodesSet.has(e.source) && nodesSet.has(e.target)
  );
  // add the edges to the selection
  selection.edges = connectedEdges;

  let errorsArray: Array<string> = [];
  // check if there is more than one node
  if (selection.nodes.length < 2) {
    errorsArray.push("Please select more than one node");
  }

  //check if there are two or more nodes with free outputs
  if (
    selection.nodes.filter(
      (n) => !selection.edges.some((e) => e.source === n.id)
    ).length > 1
  ) {
    errorsArray.push("Please select only one node with free outputs");
  }

  // check if there is any node that does not have any connection
  if (
    selection.nodes.some(
      (node) =>
        !selection.edges.some((edge) => edge.target === node.id) &&
        !selection.edges.some((edge) => edge.source === node.id)
    )
  ) {
    errorsArray.push("Please select only nodes that are connected");
  }
  return errorsArray;
}
function updateGroupNodeTemplate(template: APITemplateType) {
  /*this function receives a template, iterates for it's items
  updating the visibility of all basic types setting it to advanced true*/
  Object.keys(template).forEach((key) => {
    let type = template[key].type;
    let input_types = template[key].input_types;
    if (
      LANGFLOW_SUPPORTED_TYPES.has(type) &&
      !template[key].required && // 非必填项group 中不展示
      !input_types
    ) {
      template[key].advanced = true;
    }
    //prevent code fields from showing on the group node
    if (type === "code") {
      template[key].show = false;
    }
  });
  return template;
}
export function mergeNodeTemplates({
  nodes,
  edges,
}: {
  nodes: NodeType[];
  edges: Edge[];
}): APITemplateType {
  /* this function receives a flow and iterate throw each node
    and merge the templates with only the visible fields
    if there are two keys with the same name in the flow, we will update the display name of each one
    to show from which node it came from
  */
  let template: APITemplateType = {};
  nodes.forEach((node) => {
    let nodeTemplate = cloneDeep(node.data.node!.template);
    Object.keys(nodeTemplate)
      .filter((field_name) => field_name.charAt(0) !== "_")
      .forEach((key) => {
        if (!isHandleConnected(edges, key, nodeTemplate[key], node.id)) {
          template[key + "_" + node.id] = nodeTemplate[key];
          template[key + "_" + node.id].proxy = { id: node.id, field: key };
          if (node.type === "groupNode") {
            template[key + "_" + node.id].display_name =
              node.data.node!.flow!.name + " - " + nodeTemplate[key].name;
          } else {
            template[key + "_" + node.id].display_name =
              //data id already has the node name on it
              nodeTemplate[key].display_name
                ? nodeTemplate[key].display_name
                : nodeTemplate[key].name
                  ? toTitleCase(nodeTemplate[key].name)
                  : toTitleCase(key);
          }
        }
      });
  });
  return template;
}
function isHandleConnected(
  edges: Edge[],
  key: string,
  field: TemplateVariableType,
  nodeId: string
) {
  /*
    this function receives a flow and a handleId and check if there is a connection with this handle
  */
  if (field.proxy) {
    if (
      edges.some(
        (e) =>
          e.targetHandle ===
          scapedJSONStringfy({
            type: field.type,
            fieldName: key,
            id: nodeId,
            proxy: { id: field.proxy!.id, field: field.proxy!.field },
            inputTypes: field.input_types,
          } as targetHandleType)
      )
    ) {
      return true;
    }
  } else {
    if (edges.some(
      (e) => e.targetHandle === `${field.type}|${key}|${nodeId}`
    )) {
      return true;
    }
  }
  return false;
}

export function generateNodeTemplate(Flow: FlowType) {
  /*
    this function receives a flow and generate a template for the group node
  */
  let template = mergeNodeTemplates({
    nodes: Flow.data!.nodes,
    edges: Flow.data!.edges,
  });
  updateGroupNodeTemplate(template);
  return template;
}

export function generateNodeFromFlow(
  flow: FlowType,
  getNodeId: (type: string) => string
): NodeType {
  const { nodes } = flow.data!;
  const outputNode = cloneDeep(findLastNode(flow.data!));
  const position = getMiddlePoint(nodes);
  let data = cloneDeep(flow);
  const id = getNodeId(outputNode?.data.type!);
  // 检查是否有 fileinput
  const hasFileInput = flow.data.nodes.some((node) => node.data.type === "InputFileNode")

  const newGroupNode: NodeType = {
    data: {
      id,
      type: hasFileInput ? 'InputFileNode' : outputNode?.data.type!,
      node: {
        output_types: outputNode!.data.node!.output_types,
        display_name: "Group",
        documentation: "",
        base_classes: outputNode!.data.node!.base_classes,
        description: outputNode.data.node.description,
        template: generateNodeTemplate(data),
        flow: data,
      },
    },
    id,
    position,
    type: "genericNode",
  };
  return newGroupNode;
}

export function connectedInputNodesOnHandle(
  nodeId: string,
  handleId: string,
  { nodes, edges }: { nodes: NodeType[]; edges: Edge[] }
) {
  const connectedNodes: Array<{ name: string; id: string; isGroup: boolean }> =
    [];
  // return the nodes connected to the input handle of the node
  const TargetEdges = edges.filter((e) => e.target === nodeId);
  TargetEdges.forEach((edge) => {
    if (edge.targetHandle === handleId) {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      if (sourceNode) {
        if (sourceNode.type === "groupNode") {
          let lastNode = findLastNode(sourceNode.data.node!.flow!.data!);
          while (lastNode && lastNode.type === "groupNode") {
            lastNode = findLastNode(lastNode.data.node!.flow!.data!);
          }
          if (lastNode) {
            connectedNodes.push({
              name: sourceNode.data.node!.flow!.name,
              id: lastNode.id,
              isGroup: true,
            });
          }
        } else {
          connectedNodes.push({
            name: sourceNode.data.type,
            id: sourceNode.id,
            isGroup: false,
          });
        }
      }
    }
  });
  return connectedNodes;
}

function updateProxyIdsOnTemplate(
  template: APITemplateType,
  idsMap: { [key: string]: string }
) {
  Object.keys(template).forEach((key) => {
    if (template[key].proxy && idsMap[template[key].proxy!.id]) {
      template[key].proxy!.id = idsMap[template[key].proxy!.id];
    }
  });
}

function updateEdgesIds(edges: Edge[], idsMap: { [key: string]: string }) {
  edges.forEach((edge) => {
    let targetHandle: targetHandleType = edge.data.targetHandle;
    if (targetHandle.proxy && idsMap[targetHandle.proxy!.id]) {
      targetHandle.proxy!.id = idsMap[targetHandle.proxy!.id];
    }
    edge.data.targetHandle = targetHandle;
    edge.targetHandle = scapedJSONStringfy(targetHandle);
  });
}

// （新）
export function processFlowEdges(flow: FlowType) {
  if (!flow.data || !flow.data.edges) return;
  if (checkOldEdgesHandles(flow.data.edges)) {
    const newEdges = updateEdgesHandleIds(flow.data);
    flow.data.edges = newEdges;
  }
  //update edges colors
  flow.data.edges.forEach((edge) => {
    edge.className = "";
    edge.style = { stroke: "#555" };
  });
}

export function expandGroupNode(
  id: string,
  flow: FlowType,
  template: APITemplateType,
  nodes: Node[],
  edges: Edge[],
  setNodes: (update: Node[] | ((oldState: Node[]) => Node[])) => void,
  setEdges: (update: Edge[] | ((oldState: Edge[]) => Edge[])) => void
) {
  // const idsMap = updateIds(flow!.data!);
  // updateProxyIdsOnTemplate(template, idsMap);
  let flowEdges = edges;
  // updateEdgesIds(flowEdges, idsMap);
  const gNodes: NodeType[] = cloneDeep(flow?.data?.nodes!);
  const gEdges = cloneDeep(flow!.data!.edges);
  //redirect edges to correct proxy node
  let updatedEdges: Edge[] = [];
  flowEdges.forEach((edge) => {
    let newEdge = cloneDeep(edge);
    // group 组件输入线
    if (newEdge.target === id) {
      const targetHandleArr = newEdge.targetHandle.split("|");
      const _index = targetHandleArr[1].lastIndexOf('_');
      const tempField = targetHandleArr[1].slice(0, _index)
      const nodeId = targetHandleArr[1].slice(_index + 1)
      targetHandleArr[1] = tempField
      targetHandleArr[2] = nodeId

      newEdge.target = nodeId
      newEdge.targetHandle = targetHandleArr.join('|')

      // const targetHandle: targetHandleType = newEdge.targetHandle;
      // if (targetHandle.proxy) {
      //   let type = targetHandle.type;
      //   let field = targetHandle.proxy.field;
      //   let proxyId = targetHandle.proxy.id;
      //   let inputTypes = targetHandle.inputTypes;
      //   let node: NodeType = gNodes.find((n) => n.id === proxyId)!;
      //   if (node) {
      //     newEdge.target = proxyId;
      //     let newTargetHandle: targetHandleType = {
      //       fieldName: field,
      //       type,
      //       id: proxyId,
      //       inputTypes: inputTypes,
      //     };
      //     if (node.data.node?.flow) {
      //       newTargetHandle.proxy = {
      //         field: node.data.node.template[field].proxy?.field!,
      //         id: node.data.node.template[field].proxy?.id!,
      //       };
      //     }
      //     newEdge.data.targetHandle = newTargetHandle;
      //     newEdge.targetHandle = scapedJSONStringfy(newTargetHandle);
      //   }
      // }
    }
    // group 组件输出线
    if (newEdge.source === id) {
      const lastNode = cloneDeep(findLastNode(flow!.data!));
      newEdge.source = lastNode!.id;
      const sourceHandleArr = newEdge.sourceHandle.split('|')
      sourceHandleArr[1] = lastNode!.id;

      // newEdge.data.sourceHandle = newSourceHandle;
      newEdge.sourceHandle = sourceHandleArr.join('|');
    }
    if (edge.target === id || edge.source === id) {
      updatedEdges.push(newEdge);
    }
  });
  //update template values
  Object.keys(template).forEach((key) => {
    let { field, id } = template[key].proxy!;
    let nodeIndex = gNodes.findIndex((n) => n.id === id);
    if (nodeIndex !== -1) {
      let proxy: { id: string; field: string } | undefined;
      let display_name: string | undefined;
      let show = gNodes[nodeIndex].data.node!.template[field].show;
      let advanced = gNodes[nodeIndex].data.node!.template[field].advanced;
      if (gNodes[nodeIndex].data.node!.template[field].display_name) {
        display_name =
          gNodes[nodeIndex].data.node!.template[field].display_name;
      } else {
        display_name = gNodes[nodeIndex].data.node!.template[field].name;
      }
      if (gNodes[nodeIndex].data.node!.template[field].proxy) {
        proxy = gNodes[nodeIndex].data.node!.template[field].proxy;
      }
      gNodes[nodeIndex].data.node!.template[field] = template[key];
      gNodes[nodeIndex].data.node!.template[field].show = show;
      gNodes[nodeIndex].data.node!.template[field].advanced = advanced;
      gNodes[nodeIndex].data.node!.template[field].display_name = display_name;
      // keep the nodes selected after ungrouping
      // gNodes[nodeIndex].selected = false;
      if (proxy) {
        gNodes[nodeIndex].data.node!.template[field].proxy = proxy;
      } else {
        delete gNodes[nodeIndex].data.node!.template[field].proxy;
      }
    }
  });

  const filteredNodes = [...nodes.filter((n) => n.id !== id), ...gNodes];
  const filteredEdges = [
    ...edges.filter((e) => e.target !== id && e.source !== id),
    ...gEdges,
    ...updatedEdges,
  ];
  setNodes(filteredNodes);
  setEdges(filteredEdges);
}

export function getGroupStatus(
  flow: FlowType,
  ssData: { [key: string]: { valid: boolean; params: string } }
) {
  let status = { valid: true, params: "Built sucessfully ✨" };
  const { nodes } = flow.data!;
  const ids = nodes.map((n: NodeType) => n.data.id);
  ids.forEach((id) => {
    if (!ssData[id]) {
      status = ssData[id];
      return;
    }
    if (!ssData[id].valid) {
      status = { valid: false, params: ssData[id].params };
    }
  });
  return status;
}

export function createFlowComponent(
  nodeData: NodeDataType,
  version: string
): FlowType {
  const flowNode: FlowType = {
    data: {
      edges: [],
      nodes: [
        {
          data: { ...nodeData, node: { ...nodeData.node, official: false } },
          id: nodeData.id,
          position: { x: 0, y: 0 },
          type: "genericNode",
        },
      ],
      viewport: { x: 1, y: 1, zoom: 1 },
    },
    description: nodeData.node?.description || "",
    name: nodeData.node?.display_name || nodeData.type || "",
    id: nodeData.id || "",
    is_component: true,
    last_tested_version: version,
    status: 0,
    write: false,
    guide_word: ""
  };
  return flowNode;
}

export function downloadNode(NodeFLow: any) {
  const element = document.createElement("a");
  const file = new Blob([JSON.stringify(NodeFLow)], {
    type: "application/json",
  });
  element.href = URL.createObjectURL(file);
  element.download = `${NodeFLow.name || NodeFLow.node.display_name}.json`;
  element.click();
}

export function updateComponentNameAndType(
  data: any,
  component: NodeDataType
) { }

export function removeFileNameFromComponents(flow: FlowType) {
  flow.data!.nodes.forEach((node: NodeType) => {
    Object.keys(node.data.node!.template).forEach((field) => {
      if (node.data.node?.template[field].type === "file") {
        node.data.node!.template[field].value = "";
      }
    });
    if (node.data.node?.flow) {
      removeFileNameFromComponents(node.data.node.flow);
    }
  });
}

export function typesGenerator(data: APIObjectType) {
  return Object.keys(data)
    .reverse()
    .reduce((acc, curr) => {
      Object.keys(data[curr]).forEach((c: keyof APIKindType) => {
        acc[c] = curr;
        // Add the base classes to the accumulator as well.
        data[curr][c].base_classes?.forEach((b) => {
          acc[b] = curr;
        });
      });
      return acc;
    }, {});
}

export function templatesGenerator(data: APIObjectType) {
  return Object.keys(data).reduce((acc, curr) => {
    Object.keys(data[curr]).forEach((c: keyof APIKindType) => {
      //prevent wrong overwriting of the component template by a group of the same type
      if (!data[curr][c].flow) acc[c] = data[curr][c];
    });
    return acc;
  }, {});
}

export function downloadFlow(
  flow: FlowType,
  flowName: string,
  flowDescription?: string
) {
  let clonedFlow = cloneDeep(flow);
  removeFileNameFromComponents(clonedFlow);
  // create a data URI with the current flow data
  const jsonString = `data:text/json;chatset=utf-8,${encodeURIComponent(
    JSON.stringify({
      ...clonedFlow,
      name: flowName,
      description: flowDescription,
    })
  )}`;

  // create a link element and set its properties
  const link = document.createElement("a");
  link.href = jsonString;
  link.download = `${flowName && flowName != "" ? flowName : flow.name}.json`;

  // simulate a click on the link element to trigger the download
  link.click();
}

export const createNewFlow = (
  flowData: ReactFlowJsonObject,
  flow: FlowType
) => {
  return {
    description: flow?.description ?? '',
    name: flow?.name ? flow.name : "Untitled document",
    data: flowData,
    id: "",
    is_component: flow?.is_component ?? false,
  };
};
