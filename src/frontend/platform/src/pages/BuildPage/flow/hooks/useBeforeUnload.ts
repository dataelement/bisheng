import type { WorkFlow } from "@/types/flow";
import { isEqual } from "lodash-es";
import { useEffect,useMemo,useRef } from "react";
import { useTranslation } from "react-i18next";
import { useBlocker,useNavigate } from "react-router-dom";
export const useBeforeUnload = (flow: WorkFlow | null, nodes: WorkFlow["nodes"], preFlow: string, onPreFlowChange: () => void) => {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const hasChanged = useMemo(() => {
        // Node edits invalidate the comparison even when the graph wrapper is reused.
        void nodes;

        if (!flow) return false;

        try {
            const oldFlowData = JSON.parse(preFlow);

            if (!oldFlowData) return true;


            const { edges, nodes } = flow
            const { edges: oldEdges, nodes: oldNodes } = oldFlowData


            return !(isEqual(edges, oldEdges) && nodes.every((node, i) =>
                isEqual(node.data, oldNodes[i].data)));
        } catch {
            return true;
        }
    }, [preFlow, nodes, flow]);

    // Ask before unload only with unsaved changes: the browser dialog otherwise
    // shows on every reload or back step that leaves the page.
    useEffect(() => {
        if (!hasChanged) return
        const fun = (e: BeforeUnloadEvent) => {
            const confirmationMessage = `${t('flow.unsavedChangesConfirmation')}`;
            e.returnValue = confirmationMessage; // Compatible with different browsers
            return confirmationMessage;
        }
        window.addEventListener('beforeunload', fun);
        return () => { window.removeEventListener('beforeunload', fun) }
    }, [hasChanged, t])


    const isReturningRef = useRef(false);
    const handleReturn = () => {
        onPreFlowChange();
        isReturningRef.current = true;
    };


    useEffect(() => {
        if (!isReturningRef.current) return;

        isReturningRef.current = false;
        if (window.history.length > 1) window.history.back();
        else navigate('/build/apps');
    }, [nodes, navigate]);

    return {
        returnPage: handleReturn,
        blocker: useBlocker(hasChanged),
        hasChanged
    }
}
