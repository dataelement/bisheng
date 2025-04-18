import { Combine } from "lucide-react";
import { useEffect, useState } from "react";
import { NodeToolbar } from "@xyflow/react";
export default function SelectionMenu({ onClick, nodes, isVisible }) {
  const [isOpen, setIsOpen] = useState(false);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [lastNodes, setLastNodes] = useState(nodes);

  // nodes get saved to not be gone after the toolbar closes
  useEffect(() => {
    setLastNodes(nodes);
  }, [isOpen]);

  // transition starts after and ends before the toolbar closes
  useEffect(() => {
    if (isVisible) {
      setIsOpen(true);
      setTimeout(() => {
        setIsTransitioning(true);
      }, 50);
    } else {
      setIsTransitioning(false);
      setTimeout(() => {
        setIsOpen(false);
      }, 500);
    }
  }, [isVisible]);

  return (
    <NodeToolbar
      isVisible={isOpen}
      offset={5}
      nodeId={
        lastNodes && lastNodes.length > 0 ? lastNodes.map((n) => n.id) : []
      }
    >
      <div className="overflow-hidden">
        <div
          className={
            "duration-400 rounded-full border border-gray-200 bg-background px-2.5 text-primary shadow-inner transition-all ease-in-out" +
            (isTransitioning ? " opacity-100" : " opacity-0 ")
          }
        >
          <button
            className="flex gap-2 leading-8 items-center justify-between text-sm hover:scale-110 transition-all ease-in-out"
            onClick={onClick}
          >
            <Combine
              strokeWidth={2}
              size={16}
              className="text-primary"
            />
            Group
          </button>
        </div>
      </div>
    </NodeToolbar>
  );
}
