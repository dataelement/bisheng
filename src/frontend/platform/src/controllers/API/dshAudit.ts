import request from '@/controllers/request'
import {
    auditActions,
    auditStatuses,
    type DshAuditPage,
    type DshAuditQuery,
} from '@/types/dshAudit'

const nullableText = (value: unknown) =>
    value === null || typeof value === 'string'
const positiveId = (value: unknown) =>
    typeof value === 'number' && Number.isSafeInteger(value) && value > 0
const snapshot = (value: unknown) =>
    !!value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.values(value).every(
        (item) =>
            item === null ||
            ['string', 'number', 'boolean'].includes(typeof item),
    )

export async function getDshAuditRecords(
    query: DshAuditQuery,
    signal?: AbortSignal,
): Promise<DshAuditPage> {
    const page: DshAuditPage = await request.get(
        '/api/v1/dsh/admin/audit-records',
        { params: query, signal },
    )
    if (
        !page ||
        !Array.isArray(page.data) ||
        page.data.length > query.limit ||
        page.page_size !== query.limit ||
        typeof page.has_more !== 'boolean' ||
        !nullableText(page.next_cursor) ||
        (page.has_more ? !page.next_cursor : page.next_cursor !== null) ||
        new Set(page.data.map((row) => row?.id)).size !== page.data.length ||
        page.data.some(
            (row) =>
                !row ||
                typeof row.id !== 'string' ||
                !row.id ||
                typeof row.created_at !== 'string' ||
                !Number.isFinite(Date.parse(row.created_at)) ||
                !auditActions.includes(row.action) ||
                !auditStatuses.includes(row.status) ||
                !['USER', 'DEPARTMENT', 'ROLE'].includes(row.target_type) ||
                !positiveId(row.target_id) ||
                (row.actor_id !== null && !positiveId(row.actor_id)) ||
                (row.model_id !== null && !positiveId(row.model_id)) ||
                !nullableText(row.actor_name) ||
                !nullableText(row.target_name) ||
                !nullableText(row.model_name) ||
                !nullableText(row.result_code) ||
                !snapshot(row.before_values) ||
                !snapshot(row.after_values) ||
                !snapshot(row.requested_values),
        )
    ) {
        throw new Error('Invalid DSH audit response')
    }
    return page
}
