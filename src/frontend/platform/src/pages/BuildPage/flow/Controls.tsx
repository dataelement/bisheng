import { FileIcon, Maximize, ZoomIn, ZoomOut } from "lucide-react";
import { forwardRef } from "react";

import { Button } from "@/components/bs-ui/button";
import { cn } from "@/util/utils";
import {
    Panel,
    PanelProps,
    useReactFlow,
    useStore,
    useViewport,
} from "@xyflow/react";

export const Controls = forwardRef<
    HTMLDivElement,
    Omit<PanelProps, "children"> & { onCreateNote: () => void }
>(({ className, ...props }) => {
    // const { zoom } = useViewport();
    const { zoomTo, zoomIn, zoomOut, fitView } = useReactFlow();

    const { minZoom, maxZoom } = useStore(
        (state) => ({
            minZoom: state.minZoom,
            maxZoom: state.maxZoom,
        }),
        (a, b) => a.minZoom !== b.minZoom || a.maxZoom !== b.maxZoom,
    );

    return (
        <Panel
            className={cn(
                "flex gap-1 rounded-md bg-background  p-1 text-foreground left-52 selelct-none",
                className,
            )}
            {...props}
        >
            <Button
                variant="ghost"
                size="icon"
                onClick={() => zoomIn({ duration: 300 })}
            >
                <ZoomIn className="size-5" />
            </Button>
            {/* <Button
                className="min-w-20 tabular-nums"
                variant="ghost"
                onClick={() => zoomTo(1, { duration: 300 })}
            >
                {(100 * zoom).toFixed(0)}%
            </Button> */}
            <Button
                variant="ghost"
                size="icon"
                onClick={() => zoomOut({ duration: 300 })}
            >
                <ZoomOut className="size-5" />
            </Button>
            <Button
                variant="ghost"
                size="icon"
                onClick={() => fitView({ duration: 300 })}
            >
                <Maximize className="size-5" />
            </Button>
            <Button
                variant="ghost"
                size="icon"
                onClick={props.onCreateNote}
            >
                <span>+</span>
                <FileIcon className="size-5 ml-0.5" />
            </Button>
        </Panel>
    );
});

Controls.displayName = "Controls";