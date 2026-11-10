import { useLocalize } from '~/hooks';
import { parseFailureInfo } from '~/utils/failureInfo';

interface FailureInfoDetailsProps {
    failureInfo?: unknown;
}

const OPERATIONS = new Set(['search', 'read_file', 'invoke_model', 'parse_file', 'write_file', 'authenticate', 'transcribe', 'synthesize', 'enqueue', 'upload', 'download', 'rerank', 'embed', 'tool_call']);

const SERVICES = new Set(['database', 'mysql', 'dm8', 'redis', 'milvus', 'elasticsearch', 'llm', 'embedding', 'rerank', 'asr', 'tts', 'minio', 'transport', 'browser_connection', 'sso', 'object_storage', 'model_service', 'network', 'etl4lm', 'bisheng_knowledge', 'openfga']);

/** Only public, validated metadata is displayed; unknown operation tokens stay hidden. */
export function FailureInfoDetails({ failureInfo }: FailureInfoDetailsProps) {
    const localize = useLocalize();
    const info = parseFailureInfo(failureInfo);
    if (!info) return null;
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
