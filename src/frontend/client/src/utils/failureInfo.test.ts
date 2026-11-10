import { dailyFailureMetadata, localizedBusinessFailure, createBrowserNetworkFailure, parseFailureInfo, failureMetadataEqual, taskFailureMetadata, requestFailureMetadata } from './failureInfo';

const failure = { version: 1, failure_id: 'failure-1', category: 'database', service: 'milvus', occurred_at: '2026-11-05T08:00:00+08:00' };

describe('failure metadata boundary', () => {
    it('preserves the same identity and time across validated snapshots', () => {
        expect(parseFailureInfo(JSON.parse(JSON.stringify(failure)))).toEqual(failure);
    });
    it.each([{ version: 2 }, { category: 'unknown' }, { failure_id: '' }, { occurred_at: 'today' }, { occurred_at: '2026-11-05T08:00:00' }, { service_name: 12 }])('ignores invalid metadata without throwing: %o', (change) => {
        expect(parseFailureInfo({ ...failure, ...change })).toBeUndefined();
    });
    it('retains recovery fields independently of service classification', () => {
        expect(taskFailureMetadata({ error_type: 'rate_limit', attempt_id: 'attempt', failure_info: failure })).toMatchObject({ error_type: 'rate_limit', attempt_id: 'attempt', failure_info: failure });
    });
    it('accepts a failed task with only a service classification', () => {
        expect(taskFailureMetadata({ failure_info: failure })?.failure_info).toEqual(failure);
    });
    it('strips future version-one extension fields and null optional values', () => {
        expect(parseFailureInfo({ ...failure, service_name: null, private_detail: 'hidden' })).toEqual(failure);
    });
    it('rejects identifiers and labels containing private diagnostics', () => {
        expect(parseFailureInfo({ ...failure, trace_id: 'password=secret' })).toBeUndefined();
        expect(parseFailureInfo({ ...failure, service_name: 'Authorization: bearer secret' })).toBeUndefined();
    });
    it('creates a safe browser network event without inferring a server service', () => {
        const metadata = createBrowserNetworkFailure();
        expect(metadata.category).toBe('network');
        expect(metadata.service).toBe('transport');
        expect(parseFailureInfo(metadata)).toEqual(metadata);
    });
    it('does not infer SSO from an HTTP authentication response', () => {
        expect(requestFailureMetadata({ response: { status: 401, data: { status_code: 401, status_message: 'unauthorized' } } })?.failure_info).toBeUndefined();
    });
    it('preserves trusted HTTP metadata and recovery identities', () => {
        expect(requestFailureMetadata({ response: { data: { status_code: 11090, data: { failure_info: failure, attempt_id: 'attempt-1' } } } })).toMatchObject({ failure_info: failure, error_code: 11090, attempt_id: 'attempt-1' });
    });
});

describe('business and recovery projection', () => {
    it('uses registered business copy and never accepts raw server text', () => {
        const localize = (key: string) => key === 'api_errors.12045' ? 'Department concurrency limit' : key;
        expect(localizedBusinessFailure(12045, localize)).toBe('Department concurrency limit');
        expect(localizedBusinessFailure(99999, localize)).toBeUndefined();
        expect(localizedBusinessFailure(18106, localize)).toBeUndefined();
    });
    it('keeps every live recovery identity next to the same failure metadata', () => {
        expect(dailyFailureMetadata({failure_info: failure, execution_id:'e', attempt_id:'a', recovery_subject_id:'s', model_id:7, rate_limit_state:'busy', resume_mode:'retry'})).toMatchObject({
            failureInfo:failure,executionId:'e',attemptId:'a',recoverySubjectId:'s',modelId:7,rateLimitState:'busy',resumeMode:'retry',
        });
    });
});

it('classifies a confirmed request transport failure once and keeps its identity', () => {
    const error = {code:'ERR_NETWORK'};
    expect(requestFailureMetadata(error)?.failure_info?.category).toBe('network');
    expect(requestFailureMetadata(error)?.failure_info).toEqual(requestFailureMetadata(error)?.failure_info);
    expect(requestFailureMetadata({message:'Connection error'})?.failure_info).toBeUndefined();
});

it('invalidates a memoized step when only failure metadata changes', () => {
    expect(failureMetadataEqual(failure, JSON.parse(JSON.stringify(failure)))).toBe(true);
    expect(failureMetadataEqual(undefined, failure)).toBe(false);
    expect(failureMetadataEqual(failure, { ...failure, category: 'model_service' })).toBe(false);
});
