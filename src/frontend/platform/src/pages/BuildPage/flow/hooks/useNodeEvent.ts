import type { WorkflowNode } from "@/types/flow";
import { findParallelNodes } from "@/util/flowUtils";
import { useEffect,useRef } from "react";
import { useTranslation } from "react-i18next";

interface ValidationFlow {
    nodes: { id: string; type?: string; branch?: string; data: WorkflowNode }[];
    edges: { source: string; target: string; sourceHandle?: string | null }[];
}
type BranchNode = { branch: string; nodeId: string; type: string };
export const useNodeEvent = (flow: ValidationFlow) => {
    const { t } = useTranslation('flow');

    const nodeValidateEntitiesRef = useRef<Record<string, () => Promise<string[]> | string[]>>({});
    useEffect(() => {
        const setNodeEvent = (event: Event) => {
            const e = event as CustomEvent<{ action: string; id: string; validate: () => Promise<string[]> | string[] }>;
            const { action, id } = e.detail;
            if (action === 'update') {
                nodeValidateEntitiesRef.current[id] = e.detail.validate;
            } else {
                delete nodeValidateEntitiesRef.current[id];
            }
        };
        window.addEventListener('node_event', setNodeEvent);
        return () => {
            window.removeEventListener('node_event', setNodeEvent);
        };
    }, []);

    return async () => {
        let errors: string[] = [];

        const promises = Object.keys(nodeValidateEntitiesRef.current).map(async (key) => {
            const result = await nodeValidateEntitiesRef.current[key]();


            if (result && result.length > 0) {
                errors = [...errors, ...result];
            }
        });
        await Promise.all(promises);

        // event func
        const sendEvent = (ids: unknown) => {
            const event = new CustomEvent('nodeErrorBorderEvent', {
                detail: {
                    nodeIds: ids
                }
            });
            window.dispatchEvent(event);
        };

        if (errors.length) return errors;
        if (!flow.edges.length) {
            sendEvent([flow.nodes.find(node => node.data.type === 'start')!.id]);
            return [t('missingEndNode')];
        }


        const branchLines: { branch: string, nodeIds: { branch: string, nodeId: string; type: string }[], end: boolean }[] = [];
        const nodeMap: Record<string, boolean> = {};
        const treeNodeIdSet = new Set();
        const startEdge = flow.edges.find(node => node.source.indexOf('start') === 0);
        if (!startEdge) return [t('pleaseLinkStartNode')];
        const startNodeId = startEdge.source;
        const findEdgesByNodeId = (id: string) => {
            return flow.edges.filter(node => node.source === id);
        };
        const findOutType = (nodeId: string) => {
            if (!nodeId.startsWith('output')) return '';
            return flow.nodes.find(node => node.id === nodeId)?.data.group_params[0].params[1].value.type || '';
        };

        const traverseTree = (nodeId: string, branchId: string, nodeIds: BranchNode[]) => {
            const edges = findEdgesByNodeId(nodeId);
            edges.forEach((edge, index) => {
                const target = edge.target.split('_')[0];
                const _branchId = `${branchId}_${index}`;
                const _nodeIds = [...nodeIds, { branch: _branchId, nodeId: edge.target, type: findOutType(edge.target) }];
                treeNodeIdSet.add(edge.target);

                if (target === 'end') {
                    // stop when loop or end
                    branchLines.push({ branch: _branchId, nodeIds: _nodeIds, end: true });
                } else if (nodeMap[edge.target]) {
                    // stop when loop or end
                    branchLines.push({ branch: branchId, nodeIds, end: true });
                } else {
                    nodeMap[edge.target] = true;
                    traverseTree(edge.target, _branchId, _nodeIds);
                }
            });

            if (edges.length === 0) {
                branchLines.push({ branch: branchId, nodeIds, end: false });
            }
        };

        traverseTree(startNodeId, '0', [{ branch: '0', nodeId: startNodeId, type: '' }]);


        if (treeNodeIdSet.size !== flow.nodes.filter(node => node.type === 'flowNode').length - 1) {
            const ids = flow.nodes.reduce<string[]>((res, node) => {
                if (node.type === 'flowNode' && node.data.type !== 'start' && !treeNodeIdSet.has(node.id))
                    res.push(node.id)
                return res
            }, [])
            sendEvent(ids);
            return [t('unconnectedNodes')];
        }



        const nodeLMap: Record<string, boolean> = {};
        const [inputNodeLs, , branchNodeLs] = branchLines.reduce<[BranchNode[], BranchNode[], BranchNode[]]>(
            ([inputNodeLs, outputNodeLs, branchNodeLs], line) => {
                line.nodeIds.forEach(node => {
                    if (node.nodeId.startsWith('input')) {
                        const inputNode = flow.nodes.find(_node => _node.id === node.nodeId && _node.data.tab!.value === 'dialog_input');
                        // It is an input & ouput node and is different from the branch path in ids;
                        if (inputNode && !inputNodeLs.some(el => el.branch === inputNode.branch)) {
                            if (!nodeLMap[node.branch]) inputNodeLs.push(node);
                        }
                    } else if (node.nodeId.startsWith('output') && node.type === 'input') {
                        if (!nodeLMap[node.branch]) inputNodeLs.push(node);
                    } else if ((node.nodeId.startsWith('output') && node.type === 'choose') || node.nodeId.startsWith('condition')) {
                        if (!nodeLMap[node.branch]) branchNodeLs.push(node);
                    }
                    nodeLMap[node.branch] = true;
                });
                return [inputNodeLs, outputNodeLs, branchNodeLs];
            },
            [[], [], []]
        );

        const result = findParallelNodes(inputNodeLs, branchNodeLs);
        if (result.length) {
            sendEvent([...result, []]);
            return [t('parallelInputOutputNodes')];
        }
        // if (!result.length) {
        //     result = findParallelNodes(outputNodeLs, branchNodeLs);
        //     if (result.length) {
        //         sendEvent([...result, []]);
        //         return [t('parallelOutputNodes')];
        //     }
        // }


        const errorLine = branchLines.find(line => !line.end);
        if (errorLine) {
            sendEvent([errorLine.nodeIds[errorLine.nodeIds.length - 1].nodeId]);
            return [t('missingEndNode')];
        }


        const conditionOutputs = flow.nodes.reduce<{ name: string; nodeId: string; output: string }[]>((res, node) => {
            if (node.data.type === "condition") {
                node.data.group_params[0].params[0].value.forEach((item: { id: string }) => {
                    res.push({ name: node.data.name, nodeId: node.id, output: item.id });
                });
                res.push({ name: node.data.name, nodeId: node.id, output: "right_handle" });
            }
            return res;
        }, []);

        const incompleteNode = conditionOutputs.find(output => {
            return !flow.edges.some(edge =>
                edge.source === output.nodeId && edge.sourceHandle === output.output
            );
        });
        if (incompleteNode) {
            sendEvent(incompleteNode.nodeId);
            return [t('unconnectedConditionNode', { nodeName: incompleteNode.name })];
        }

        sendEvent([]); // reduction
        return errors;
    };
};
