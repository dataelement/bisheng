import { Button } from "@/components/bs-ui/button";
import { Card, CardContent } from "@/components/bs-ui/card";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Position } from "@xyflow/react";
import { Plus } from "lucide-react";
import Sidebar from "./Sidebar";
export default function CustomEdge({ id, sourceX, sourceY, targetX, targetY, onOptionSelect, onButtonClick, isDropdownOpen }) {
    const [edgePath, labelX, labelY] = getBezierPath({
        sourceX,
        sourceY,
        sourcePosition: Position.Right,
        targetX,
        targetY,
        targetPosition: Position.Left,
        curvature: 0.4
    });

    const handleOptionClick = (option) => {
        onOptionSelect({ label: option, position: { x: labelX, y: labelY } });
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
                style={{ stroke: '#024de3', strokeWidth: 1 }}
                markerEnd="url(#arrow)"
            />
            {/* 在连线中间添加一个加号按钮 */}
            {/* <EdgeLabelRenderer>
                <div
                    className="absolute"
                    style={{
                        transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
                        zIndex: 1000
                    }}
                >
                    <Button size="icon" className="rounded-full w-6 h-6 pointer-events-auto" onClick={() => onButtonClick(id)}>
                        <Plus size={18} className="text-[#fff]" />
                    </Button>
                    {isDropdownOpen && <Card className="absolute top-10 translate-x-[-50%] bg-transparent hover:shadow-none" style={{ zIndex: 1001 }}>
                        <CardContent className="min-w-56 pointer-events-auto px-0">
                            <Sidebar dropdown onClick={(key) => handleOptionClick(key)}></Sidebar>
                        </CardContent>
                    </Card>}
                </div>
            </EdgeLabelRenderer> */}
        </>
    );
};