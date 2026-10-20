import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import i18next, { TFunction } from "i18next";

/** `subflow_warning` returned when a workflow used as a subflow is saved or switched to another version. */
export interface SubflowWarning {
    referenced_by: { id: string, name: string }[]
    forbidden_nodes: { id: string, name: string, type: string }[]
    interface_changes: {
        inputs_added: string[]
        inputs_removed: string[]
        outputs_added: string[]
        outputs_removed: string[]
    }
}

const CHANGE_KINDS = ['inputs_added', 'inputs_removed', 'outputs_added', 'outputs_removed'] as const

/** The paragraphs of the warning, in display order. */
export function subflowWarningLines(warning: SubflowWarning, t: TFunction): string[] {
    const separator = t('subflowWarning.separator')
    const join = (names: string[]) => names.join(separator)
    const lines = [t('subflowWarning.referencedBy', { names: join(warning.referenced_by.map(one => one.name)) })]
    if (warning.forbidden_nodes.length) {
        lines.push(t('subflowWarning.forbiddenNodes', { names: join(warning.forbidden_nodes.map(one => one.name)) }))
    }
    CHANGE_KINDS.forEach(kind => {
        const names = warning.interface_changes?.[kind] || []
        if (names.length) lines.push(t(`subflowWarning.${kind}`, { names: join(names) }))
    })
    return lines
}

/** F086: tell the editor which workflows use this one as a subflow and what will affect them. */
export function showSubflowWarning(warning: SubflowWarning | undefined | null): void {
    if (!warning?.referenced_by?.length) return
    const t = i18next.getFixedT(null, 'flow')
    bsConfirm({
        title: t('subflowWarning.title'),
        desc: <div className="space-y-2">
            {subflowWarningLines(warning, t).map(line => <p key={line}>{line}</p>)}
        </div>,
        okTxt: t('subflowWarning.ok'),
        hideCancel: true,
    })
}
