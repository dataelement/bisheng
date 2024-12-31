import { Button } from "@/components/bs-ui/button";
import { Card, CardContent } from "@/components/bs-ui/card";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Position } from "@xyflow/react";
import { Plus } from "lucide-react";
import { useMemo } from "react";
import Sidebar from "./Sidebar";

function getUpperArcBezierPath(sourceX, sourceY, targetX, targetY) {
    const dx = Math.abs(targetX - sourceX);
    const dy = Math.abs(targetY - sourceY);

    // 控制点的偏移量
    const offsetX = dx / 2.8; // 水平控制点偏移
    const offsetY = Math.max(dy, 180); // 垂直控制点偏移，让曲线更弯曲

    // 控制点的坐标（从上方绕弧线）
    const controlX1 = sourceX + offsetX;
    const controlY1 = sourceY - offsetY; // 控制点向上偏移
    const controlX2 = targetX - offsetX;
    const controlY2 = targetY - offsetY;

    const path = `M${sourceX},${sourceY} C${controlX1},${controlY1} ${controlX2},${controlY2} ${targetX},${targetY}`;
    const centerX =
        0.125 * sourceX +
        0.375 * controlX1 +
        0.375 * controlX2 +
        0.125 * targetX;
    const centerY =
        0.125 * sourceY +
        0.375 * controlY1 +
        0.375 * controlY2 +
        0.125 * targetY;
    return [path, centerX, centerY];
}

export default function CustomEdge({
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    selected,
    onOptionSelect,
    onButtonClick,
    isDropdownOpen,
}) {

    const [edgePath, labelX, labelY] = useMemo(() => {
        return targetX > sourceX ? getBezierPath({
            sourceX,
            sourceY,
            sourcePosition: Position.Right,
            targetX,
            targetY,
            targetPosition: Position.Left,
            curvature: 0.4,
        }) : getUpperArcBezierPath(sourceX, sourceY, targetX, targetY)

    }, [sourceX, sourceY, targetX, targetY])

    const handleOptionClick = (flownodedata) => {
        onOptionSelect({
            node: flownodedata,
            edgeId: id,
            position: { x: labelX, y: labelY }
        });
    };

    return (
        <>
            {/* arrow */}
            <svg>
                <defs>
                    <marker
                        id="arrow"
                        viewBox="0 0 10 10"
                        refX="10"
                        refY="5"
                        markerWidth="6"
                        markerHeight="6"
                        orient="auto-start-reverse"
                    >
                        <path d="M 0 0 L 10 5 L 0 10 z" fill="#024de3" />
                    </marker>
                </defs>
            </svg>
            {/* 渲染默认的连线 */}
            <BaseEdge
                id={id}
                path={edgePath}
                style={{ stroke: '#024de3', strokeWidth: selected ? 2 : 1, strokeDasharray: selected && 0 }}
                markerEnd="url(#arrow)"
            />
            {/* 在连线中间添加一个加号按钮 */}
            {selected && <EdgeLabelRenderer>
                <div
                    className="absolute"
                    style={{
                        transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
                        zIndex: 1000,
                    }}
                >
                    <Button
                        size="icon"
                        className="rounded-full w-5 h-5 pointer-events-auto"
                        onClick={() => onButtonClick(id)}
                    >
                        <Plus size={18} className="text-[#fff]" />
                    </Button>
                    {isDropdownOpen && (
                        <Card
                            className="absolute top-8 translate-x-[-50%] bg-transparent hover:shadow-none hover:border-transparent"
                            style={{ zIndex: 1001 }}
                        >
                            <CardContent className="min-w-56 pointer-events-auto px-0">
                                <Sidebar
                                    dropdown
                                    disabledNodes={['end']}
                                    onClick={(flownodedata) => handleOptionClick(flownodedata)}
                                ></Sidebar>
                            </CardContent>
                        </Card>
                    )}
                </div>
            </EdgeLabelRenderer>
            }
        </>
    );
}
