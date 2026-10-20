import { TFunction } from "i18next";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import NodeLogo from "./NodeLogo";
import { ResultFile } from "./RunLog";
import { ResultText } from "./RunTest";

/** One inner node run of a subflow, as sent in the `subflow_logs` log item. */
export interface SubflowNodeLog {
    node_id: string
    name: string
    type: string
    duration_ms: number
    reason: string | null
    log_data: { key: string, value: unknown, type: string }[][] | null
    input_data: Record<string, unknown> | null
}

interface LogField {
    label: string
    type: string
    value: unknown
}

/** Fields shown for one inner node: failure reason, inputs, then every logged value of every round. */
export function subflowNodeFields(log: SubflowNodeLog, t: TFunction): LogField[] {
    const fields: LogField[] = []
    if (log.reason) fields.push({ label: t('subflowLog.reason'), type: 'text', value: log.reason })
    if (log.input_data && Object.keys(log.input_data).length) {
        fields.push({ label: t('subflowLog.input'), type: 'text', value: log.input_data })
    }
    const rounds = log.log_data || []
    rounds.forEach((round, index) => {
        const suffix = rounds.length > 1 ? ` (${t('roundRunResult', { index: index + 1 })})` : ''
        round.forEach(item => {
            const label = ['file', 'variable'].includes(item.type)
                ? item.key.split('.').pop()
                : t(`node.${log.type}.${item.key}.label`, { defaultValue: item.key })
            fields.push({ label: `${label}${suffix}`, type: item.type, value: item.value })
        })
    })
    return fields
}

export function formatDuration(ms: number): string {
    return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

const NodeRow = ({ log }: { log: SubflowNodeLog }) => {
    const { t } = useTranslation('flow')
    const [open, setOpen] = useState(Boolean(log.reason))
    const Arrow = open ? ChevronDown : ChevronRight

    return <div className="mb-1 rounded-md border bg-background">
        <div className="flex items-center gap-2 px-2 py-1 cursor-pointer text-sm" onClick={() => setOpen(!open)}>
            <Arrow size={14} className="min-w-3.5" />
            <NodeLogo type={log.type} colorStr={log.name} />
            <span className={`truncate flex-1 ${log.reason ? 'text-red-500' : ''}`}>{log.name}</span>
            <span className="text-xs text-muted-foreground">{formatDuration(log.duration_ms)}</span>
        </div>
        {open && <div className="px-2 pt-1">
            {subflowNodeFields(log, t).map((field, index) => field.type === 'file'
                ? <ResultFile key={index} title={field.label} name={log.name} fileUrl={String(field.value)} />
                : <ResultText key={index} title={field.label} value={field.value} />)}
        </div>}
    </div>
}

/** F086: the inner node runs of a subflow, each expandable to its inputs and outputs. */
export function SubflowRunLog({ title, logs }: { title: string, logs: SubflowNodeLog[] }) {
    const { t } = useTranslation('flow')
    return <div className="mb-2 rounded-md border bg-search-input text-sm shadow-sm">
        <div className="border-b px-2"><p className="truncate">{title}</p></div>
        <div className="p-2 max-h-96 overflow-y-auto nowheel">
            {logs.length
                ? logs.map((log, index) => <NodeRow key={`${log.node_id}-${index}`} log={log} />)
                : <p className="text-xs text-muted-foreground">{t('subflowLog.empty')}</p>}
        </div>
    </div>
}
