import { Label } from "@/components/bs-ui/label";
import { Switch } from "@bisheng/ui";
import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { WorkflowNode, WorkflowNodeParam } from "@/types/flow";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CodeInputItem from "./CodeInputItem";

// GraphState reads this key as the chat history, so a return value under it is unreachable.
const RESERVED_RETURN_NAMES = ["chat_history"];

interface EndReturnItemProps {
    nodeId: string
    node: WorkflowNode
    data: WorkflowNodeParam
    onChange: (value: unknown) => void
    onValidate: (validate: () => string | false) => void
    onVarEvent: (validate: () => Promise<string> | void) => void
    i18nPrefix: string
}

/**
 * F086: the End node's "return results" switch and list.
 * The switch lives in the hidden sibling param `return_enabled`; the list is only
 * shown and validated while the switch is on.
 */
export function EndReturnItem({ nodeId, node, data, onChange, onValidate, onVarEvent, i18nPrefix }: EndReturnItemProps) {
    const { t } = useTranslation('flow')
    const enabledParam = node.group_params
        .flatMap(group => group.params)
        .find(param => param.key === 'return_enabled')
    const [enabled, setEnabled] = useState<boolean>(Boolean(enabledParam?.value))
    const enabledRef = useRef(enabled)

    const handleSwitch = (checked: boolean) => {
        if (enabledParam) enabledParam.value = checked
        enabledRef.current = checked
        setEnabled(checked)
    }

    const handleValidate = (validate: () => string | false) => {
        onValidate(() => (enabledRef.current ? validate() : false))
    }

    const handleVarEvent = (validate: () => Promise<string> | void) => {
        onVarEvent(() => (enabledRef.current ? validate() : Promise.resolve('')))
    }

    const validateName = (name: string) =>
        RESERVED_RETURN_NAMES.includes(name) ? t(`${i18nPrefix}reservedName`, { name }) : false

    return <div className='node-item mb-4' data-key={data.key}>
        <div className="flex justify-between items-center mb-2">
            <Label className="flex items-center bisheng-label">
                {t(`${i18nPrefix}label`)}
                <QuestionTooltip content={t(`${i18nPrefix}help`)} />
            </Label>
            <Switch checked={enabled} onCheckedChange={handleSwitch} />
        </div>
        {enabled && <CodeInputItem
            nodeId={nodeId}
            data={data}
            onChange={onChange}
            onValidate={handleValidate}
            onVarEvent={handleVarEvent}
            i18nPrefix={i18nPrefix}
            refOnly
            validateName={validateName}
        />}
    </div>
}
