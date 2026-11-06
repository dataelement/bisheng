import { Button } from '@bisheng/ui';

import { FlowTooltip as Tip } from "@/pages/BuildPage/flow/FlowTooltip";
import { Filled, Outlined } from "bisheng-icons";

import { useTranslation } from "react-i18next";

export default function NodeToolbarComponent({ nodeId, type, onRun }) {
    const { t } = useTranslation('flow')
    const handleDelete = () => {
        const event = new CustomEvent('nodeDelete', {
            detail: nodeId
        });
        window.dispatchEvent(event);
    }

    const handleCopy = () => {
        const event = new CustomEvent('nodeCopy', {
            detail: [nodeId]
        });
        window.dispatchEvent(event);
    }

    if (type === 'start') return null

    return <div className="rounded-xl shadow-sm p-1 bg-gradient-to-r from-gray-50 to-[#fff] dark:from-gray-900 dark:to-gray-950 border">
        {["agent", "tool", "llm", "rag", "qa_retriever", "code"].includes(type) && (
            <Tip content={t('runNode')} side="top">
                <Button size="medium" variant="text" className="size-8" onClick={onRun} color="default" iconOnly>
                    <Filled.PlayerPlay size={16} />
                </Button>
            </Tip>
        )}
        <Tip content={t('copy')} side="top">
            <Button size="medium" variant="text" className={`size-8`} onClick={handleCopy} color="default" iconOnly>
                <Outlined.Copy size={16} />
            </Button>
        </Tip>
        <Tip content={t('delete')} side="top">
            <Button size="medium" variant="text" className={`size-8 hover:text-red-600`} onClick={handleDelete} color="default" iconOnly>
                <Outlined.Delete size={16} />
            </Button>
        </Tip>
    </div>
};
