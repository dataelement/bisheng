// @ts-strict-ignore
import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { useKnowledgeCandidates } from "@/components/bs-comp/selectComponent/useKnowledgeCandidates";
import { isVarInFlow } from "@/util/flowUtils";
import { Tabs, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";

export function hasTempKnowledgeMode(fileParseMode: unknown): boolean {
    return Array.isArray(fileParseMode) ? fileParseMode.includes('ingest_to_temp_kb') : fileParseMode === 'ingest_to_temp_kb';
}

export default function KnowledgeSelectItem({ data, nodeId, onChange, onVarEvent, onValidate, i18nPrefix }) {
    const { flow } = useFlowStore();
    const { t } = useTranslation('flow');
    const [tabType, setTabType] = useState(data.value.type === 'tmp' ? 'tmp' : 'space');
    const [value, setValue] = useState(() => data.value.value.map(el => ({ label: el.label, value: el.key })));
    const currentMode = useRef(data.value.type);
    const candidates = useKnowledgeCandidates('space', tabType !== 'tmp');
    const saved = new Map(value.map(item => [String(item.value), item]));
    const options = candidates.options.map(item => ({ ...item, value: saved.get(String(item.value))?.value ?? item.value }));
    const [fileOptions, setFileOptions] = useState([]);
    useEffect(() => {
        currentMode.current = data.value.type;
        setValue(data.value.value.map(el => ({ label: el.label, value: el.key })));
    }, [data.value]);
    // Temporary input variables keep their existing mode.
    const loadFiles = () => {
        const files = []
        flow.nodes.forEach(node => {
            if (node.data.type !== 'input') return
            if (node.data.tab.value === "dialog_input") return
            node.data.group_params.forEach(group => {
                group.params.forEach(param => {
                    if (param.key === 'form_input') {
                        param.value.forEach(val => {
                            if (val.type === 'file' && hasTempKnowledgeMode(val.file_parse_mode)) {
                                files.push({
                                    label: `${val.key}(${val.value})`,
                                    value: `${node.id}.${val.key}`
                                })
                            }
                        })
                    }
                })
            })
        })
        setFileOptions(files)
    }


    useEffect(() => { loadFiles(); }, [flow.nodes]);
    const handleSelect = (vals) => {
        const added = vals.filter(item => !saved.has(String(item.value)));
        const switchedTemp = (currentMode.current === 'tmp') !== (tabType === 'tmp');
        const next = added.length && switchedTemp ? added : vals;
        const mode = added.length ? tabType : currentMode.current;
        setValue(next);
        onChange({ ...data.value, type: mode, value: next.map(item => ({ key: item.value, label: item.label })) });
        currentMode.current = mode;
    };
    const [error, setError] = useState(false);
    useEffect(() => {
        onValidate(() => {
            if (data.required && !data.value.value.length) {
                setError(true);
                return `${t(`${i18nPrefix}label`)} ${t('required')}`;
            }
            if (data.value.value.some(item => /input_[a-zA-Z0-9]+\.file/.test(item.key))) return 'input_file';
            setError(false);
            return false;
        });
        return () => onValidate(() => {});
    }, [data.value]);
    const [errorKeys, setErrorKeys] = useState([]);
    useEffect(() => {
        onVarEvent?.((config) => {
            // Saved numeric references are checked by the authoritative execution path.
            // A partial visible candidate page cannot establish that an old target was deleted.
            if (data.value.type !== 'tmp') return '';
            if (config?.tmp && value.length) {
                setError(true);
                return t('tmpKnowledgeBaseNotSupportSingleNodeDebug');
            }
            const invalid = value.filter(item => isVarInFlow(nodeId, flow.nodes, item.value, ''));
            setErrorKeys(invalid.map(item => item.value));
            return invalid.length ? isVarInFlow(nodeId, flow.nodes, invalid[0].value, '') : '';
        });
        return () => onVarEvent?.(() => {});
    }, [data, value, flow.nodes]);
    return <div className="node-item mb-4">
        <Label className="flex items-center bisheng-label mb-2">
            {data.required && <span className="text-red-500">*</span>}{t(`${i18nPrefix}label`)}
        </Label>
        <MultiSelect id="knowledge-select-item" error={error} errorKeys={errorKeys} multiple
            value={value} options={tabType === 'tmp' ? fileOptions : options}
            hideSearch={tabType === 'tmp'}
            tabs={<Tabs activeKey={tabType} onChange={setTabType} className="mb-2" items={[
                { key: 'space', label: t('knowledgeSpace') },
                { key: 'tmp', label: <Tooltip content={t('storeFilesSentInCurrentSession')}>
                    <span className="inline-flex items-center gap-1">{t('temporarySessionFiles')}<Outlined.Question size={14} className="text-text-3" /></span>
                </Tooltip> },
            ]} />}
            placeholder={data.placeholder ? t(`${i18nPrefix}placeholder`) : ''}
            searchPlaceholder={t('build.searchBaseName', { ns: 'bs' })}
            onChange={handleSelect} onLoad={() => { candidates.refresh(); loadFiles(); }}
            onSearch={candidates.search} onScrollLoad={candidates.loadMore} />
        {data.value.type !== 'tmp' && value.some(item => !options.some(option => String(option.value) === String(item.value))) &&
            <p className="text-xs text-text-3">{t('references.unconfirmed', { ns: 'bs' })}</p>}
    </div>;
}
