import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { parseFailureInfo } from '~/utils/failureInfo';

interface FailureInfoDetailsProps {
    failureInfo?: unknown;
    /** Support reference for a failure without dependency provenance; shown
        only when there is no valid failureInfo. */
    referenceId?: string;
}

const OPERATIONS = new Set(['search', 'read_file', 'invoke_model', 'parse_file', 'write_file', 'authenticate', 'transcribe', 'synthesize', 'enqueue', 'upload', 'download', 'rerank', 'embed', 'tool_call']);

const SERVICES = new Set(['database', 'mysql', 'dm8', 'redis', 'milvus', 'elasticsearch', 'llm', 'embedding', 'rerank', 'asr', 'tts', 'minio', 'transport', 'browser_connection', 'sso', 'object_storage', 'model_service', 'network', 'etl4lm', 'bisheng_knowledge', 'openfga']);

/** Only public, validated metadata is displayed; unknown operation tokens stay hidden. */
export function FailureInfoDetails({ failureInfo, referenceId }: FailureInfoDetailsProps) {
    const localize = useLocalize();
    const info = parseFailureInfo(failureInfo);
    if (!info) {
        if (!referenceId || !/^[A-Za-z0-9_-]{1,128}$/.test(referenceId)) return null;
        return <p className="mt-1 break-all text-caption text-text-3">{localize('api_errors.failure_id', { 0: referenceId })}</p>;
    }
    const serviceNameKey = info.service_name?.toLowerCase();
    const serviceName = serviceNameKey && SERVICES.has(serviceNameKey)
        ? localize(`api_errors.failure_service_${serviceNameKey}`)
        : info.service_name;
    const parts = [
        serviceName || localize(`api_errors.failure_service_${info.service && SERVICES.has(info.service) ? info.service : info.category}`),
        info.operation && OPERATIONS.has(info.operation) ? localize(`api_errors.failure_operation_${info.operation}`) : undefined,
        info.occurred_at,
        localize('api_errors.failure_id', { 0: info.failure_id }),
        info.trace_id ? localize('api_errors.failure_trace_id', { 0: info.trace_id }) : undefined,
    ].filter(Boolean);
    return <p className="mt-1 whitespace-pre-wrap break-words text-caption text-text-3">{parts.join(' · ')}</p>;
}

/** Redacted exception text behind a "view details" toggle. The backend masks
    URLs, hosts and credentials before it sends `detail`. */
export function ErrorDetailDisclosure({ detail }: { detail?: string }) {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);
    if (!detail) return null;
    return (
        <div className="mt-2.5">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="inline-flex items-center gap-1 text-body text-gray-400 transition-colors hover:text-gray-600"
            >
                {localize(open ? 'com_linsight_error_hide_detail' : 'com_linsight_error_view_detail')}
                {open ? <Outlined.Down size={14} /> : <Outlined.Right size={14} />}
            </button>
            {open && (
                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-100 p-2.5 text-xs leading-relaxed text-gray-500">
                    {detail}
                </pre>
            )}
        </div>
    );
}
