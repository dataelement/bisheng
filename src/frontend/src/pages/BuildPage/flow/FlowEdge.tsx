import { Button } from "@/components/bs-ui/button";
import { Card, CardContent } from "@/components/bs-ui/card";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Position } from "@xyflow/react";
import Sidebar from "./Sidebar";
export default function CustomEdge({ id, sourceX, sourceY, targetX, targetY, onOptionSelect, onButtonClick, isDropdownOpen }) {
    const [edgePath, labelX, labelY] = getBezierPath({
        sourceX,
        sourceY,
        sourcePosition: Position.Right,
        targetX,
        targetY,
        targetPosition: Position.Left,
    });
    const handleOptionClick = (option) => {
        onOptionSelect({ label: option, position: { x: labelX, y: labelY } });
    };
    return (
        <>
            {/* 渲染默认的连线 */}
            <BaseEdge id={id} path={edgePath} style={{ stroke: '#024de3', strokeWidth: 2 }} />
            {/* 在连线中间添加一个加号按钮 */}
            <EdgeLabelRenderer>
                <div
                    className="absolute"
                    style={{
                        transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
                        zIndex: 1000
                    }}
                >
                    <Button size="icon" className="rounded-full w-8 h-8 pointer-events-auto" onClick={() => onButtonClick(id)}>
                        <Plus className="text-[#fff]" />
                    </Button>
                    {isDropdownOpen && <Card className="absolute top-10 translate-x-[-50%] shadow-[0_8px_16px_0px_rgba(40,47,84,0.15)]" style={{zIndex: 1001}}>
                        <CardContent className="w-56 pointer-events-auto px-0">
                            <Sidebar dropdown onClick={(key) => handleOptionClick(key)}></Sidebar>
                        </CardContent>
                    </Card>}
                </div>
            </EdgeLabelRenderer>
        </>
    );
};