import { Button } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";
import { ZoomIn,ZoomOut } from "lucide-react";
import { forwardRef } from "react";


import { cn } from "@/util/utils";
import {
Panel,
PanelProps,
useReactFlow,
useStore
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
            <Button variant="text" size="medium" onClick={() => zoomIn({ duration: 300 })} color="default" iconOnly>
                <ZoomIn className="size-5" />
            </Button>
            {/* <Button
                className="min-w-20 tabular-nums"
                variant="ghost"
                onClick={() => zoomTo(1, { duration: 300 })}
            >
                {(100 * zoom).toFixed(0)}%
            </Button> */}
            <Button variant="text" size="medium" onClick={() => zoomOut({ duration: 300 })} color="default" iconOnly>
                <ZoomOut className="size-5" />
            </Button>
            <Button variant="text" size="medium" onClick={() => fitView({ duration: 300 })} color="default" iconOnly>
                <Outlined.FullScreen className="size-5" />
            </Button>
            <Button variant="text" size="medium" className="gap-0.5" onClick={props.onCreateNote} color="default" iconOnly>
                <span>+</span>
                <Outlined.File className="size-5" />
            </Button>
        </Panel>
    );
});

Controls.displayName = "Controls";