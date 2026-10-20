import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getSubflowCandidatesApi, getSubflowInterfaceApi, SubflowInterface } from "@/controllers/API/workflow";
import { WorkflowNode, WorkflowNodeParam } from "@/types/flow";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import CodeInputItem from "./CodeInputItem";
import { applySubflowInterface, findNodeParam, SubflowInputRow } from "./subflowParams";

const PAGE_SIZE = 20

interface Option {
    label: string
    value: string
}

interface SubflowSelectItemProps {
    nodeId: string
    node: WorkflowNode
    data: WorkflowNodeParam
    onChange: (value: unknown) => void
    onValidate: (validate: () => string | false) => void
    onVarEvent: (validate: () => Promise<string> | void) => void
    i18nPrefix: string
}

/**
 * F086: pick the workflow a subflow node runs, then show its input parameters
 * (fixed names, "reference" or "input" values) and its return names.
 * The inputs and outputs live in the node's hidden params `subflow_inputs` and
 * `subflow_outputs`; the latter is what downstream variable pickers read.
 */
export function SubflowSelectItem({ nodeId, node, data, onChange, onValidate, onVarEvent, i18nPrefix }: SubflowSelectItemProps) {
    const { t } = useTranslation('flow')
    const { flow } = useFlowStore()
    const inputsParam = findNodeParam(node, 'subflow_inputs')
    const outputsParam = findNodeParam(node, 'subflow_outputs')

    const [selected, setSelected] = useState<Option[]>(() =>
        data.value?.id ? [{ label: data.value.name, value: data.value.id }] : [])
    const [outputs, setOutputs] = useState<string[]>(() => (outputsParam?.value || []).map((one: { key: string }) => one.key))
    const [inputsVersion, setInputsVersion] = useState(0)
    const [notice, setNotice] = useState('')
    const [error, setError] = useState(false)

    // candidates, loaded page by page
    const [options, setOptions] = useState<Option[]>([])
    const cursorRef = useRef<string | null>(null)
    const requestSeqRef = useRef(0)
    const loadCandidates = (cursor: string | null, name: string) => {
        const seq = ++requestSeqRef.current
        getSubflowCandidatesApi({ name, cursor, page_size: PAGE_SIZE, exclude_flow_id: flow?.id }).then(res => {
            if (seq !== requestSeqRef.current) return
            cursorRef.current = res.cursor
            const next = res.data.filter(one => one.id).map(one => ({ label: one.name, value: one.id }))
            setOptions(prev => cursor ? [...prev, ...next.filter(o => !prev.some(p => p.value === o.value))] : next)
        }).catch(() => {
            // The request layer already showed the error; stop paging past a failed page.
            if (seq === requestSeqRef.current) cursorRef.current = null
        })
    }

    const showInterface = (info: SubflowInterface) => {
        if (!inputsParam || !outputsParam) return
        applySubflowInterface(data, inputsParam, outputsParam, info)
        setOutputs(info.outputs)
        setInputsVersion(v => v + 1)
        setNotice(info.eligible ? '' : t(`${i18nPrefix}ineligible`, {
            reasons: info.ineligible_reasons.map(code => t(`${i18nPrefix}reasons.${code}`)).join(t(`${i18nPrefix}separator`)),
        }))
    }

    const interfaceSeqRef = useRef(0)
    const fetchInterface = (flowId: string, onLoaded: (info: SubflowInterface) => void) => {
        const seq = ++interfaceSeqRef.current
        getSubflowInterfaceApi(flowId).then(info => {
            // Only the latest pick counts when several answers arrive out of order.
            if (seq === interfaceSeqRef.current) onLoaded(info)
        }).catch((envelope: { status_code?: number }) => {
            // Without edit permission the saved snapshot keeps the node usable (AC-10).
            if (envelope?.status_code === 404) setNotice(t(`${i18nPrefix}notFound`))
        })
    }

    // An opened node shows what the subflow looks like now, not when it was configured.
    // Runs once per opening on purpose: later changes come from handleSelect.
    useEffect(() => {
        if (data.value?.id) fetchInterface(data.value.id, showInterface)
    }, []) // eslint-disable-line react-hooks/exhaustive-deps -- mount-only refresh

    const handleSelect = (vals: Option[]) => {
        const picked = vals[vals.length - 1]
        if (!picked) return
        setError(false)
        // The node switches only once the new workflow's interface is loaded,
        // so a failed load leaves the previous workflow and its parameters intact.
        fetchInterface(picked.value, info => {
            setSelected([picked])
            showInterface(info)
            onChange(data.value)
        })
    }

    useEffect(() => {
        onValidate(() => {
            if (data.value?.id) return false
            setError(true)
            return `${t(`${i18nPrefix}label`)} ${t('required')}`
        })
        return () => onValidate(() => false)
    }, [data.value, i18nPrefix, onValidate, t])

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className="flex items-center bisheng-label mb-2">
            <span className="text-red-500">*</span>
            {t(`${i18nPrefix}label`)}
            <QuestionTooltip content={t(`${i18nPrefix}help`)} />
        </Label>
        <MultiSelect
            id={`subflow-select-${nodeId}`}
            error={error}
            value={selected}
            options={options}
            placeholder={t(`${i18nPrefix}placeholder`)}
            searchPlaceholder={t(`${i18nPrefix}search`)}
            onChange={handleSelect}
            onLoad={() => loadCandidates(null, '')}
            onSearch={(name) => loadCandidates(null, name)}
            onScrollLoad={(name) => { if (cursorRef.current) loadCandidates(cursorRef.current, name) }}
        />
        {notice && <p className="mt-2 text-xs text-red-500">{notice}</p>}

        {/* Nothing to describe until a workflow is picked. */}
        {selected.length > 0 && inputsParam && <div className="mt-4">
            <Label className="flex items-center bisheng-label mb-2">
                {t('node.subflow.subflow_inputs.label')}
                <QuestionTooltip content={t('node.subflow.subflow_inputs.help')} />
            </Label>
            {(inputsParam.value as SubflowInputRow[]).length
                ? <CodeInputItem
                    key={inputsVersion}
                    nodeId={nodeId}
                    data={inputsParam}
                    onChange={(rows) => { inputsParam.value = rows }}
                    onValidate={() => { }}
                    onVarEvent={onVarEvent}
                    i18nPrefix="node.subflow.subflow_inputs."
                    fixedKeys
                />
                : <p className="text-xs text-muted-foreground">{t('node.subflow.subflow_inputs.empty')}</p>}
        </div>}

        {selected.length > 0 && <div className="mt-4">
            <Label className="flex items-center bisheng-label mb-2">
                {t('node.subflow.subflow_outputs.label')}
                <QuestionTooltip content={t('node.subflow.subflow_outputs.help')} />
            </Label>
            {outputs.length
                ? <div className="flex flex-wrap gap-1">
                    {outputs.map(name => <span key={name} className="rounded border px-2 py-0.5 text-xs bg-background">{name}</span>)}
                </div>
                : <p className="text-xs text-muted-foreground">{t('node.subflow.subflow_outputs.empty')}</p>}
        </div>}
    </div>
}
