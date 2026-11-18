import { KnowledgeDialogTable } from './KnowledgeDialogTable';

type Translate = (key: string) => string;

type Counts = Record<string, number>;

type DeletionItem = { id?: number | null; type?: string | null; name?: string | null };

interface KnowledgeDeletionItemsProps {
  validItems: readonly DeletionItem[];
  invalidItems: readonly (DeletionItem & { reason: string })[];
  translate: Translate;
}

interface KnowledgeReferenceTablesProps {
  impact?: { source_counts: Counts; restricted_counts: Counts; check_complete?: boolean };
  slotCounts?: Counts;
  page?: {
    has_more: boolean;
    data: readonly {
      disclosure: {
        source: {
          tenant_id: number;
          source_type: string;
          source_id: string;
          source_version: string | null;
        };
        name: string;
        version_label: string | null;
        entry: string | null;
      };
      matched_slot_count: number;
      locations?: readonly string[];
    }[];
  };
  readonly: boolean;
  deletingSpace: boolean;
  translate: Translate;
}

const sourceKinds = new Set([
  'workflow_version',
  'assistant',
  'hosted_app_version',
  'channel_sync',
  'knowledge',
  'model_default',
]);
const restrictedDeletionKinds = new Set(['knowledge', 'model_default']);
const locationCodes = new Set([
  'workflow_knowledge_retriever',
  'workflow_rag_knowledge',
  'workflow_agent_knowledge',
  'workflow_qa_retriever',
  'workflow_reference',
]);
const deletionReasons = new Set([
  'not_found',
  'type_mismatch',
  'referenced',
  'processing',
  'no_permission',
]);

export function KnowledgeDeletionItems({
  validItems,
  invalidItems,
  translate: tr,
}: KnowledgeDeletionItemsProps) {
  const name = { label: tr('item_name') };
  return (
    <>
      {validItems.length > 0 && (
        <KnowledgeDialogTable
          caption={tr('valid_items')}
          columns={[name]}
          rows={validItems.map((item) => ({
            key: `${item.type}:${item.id}`,
            cells: [item.name || tr('unnamed')],
          }))}
        />
      )}
      {invalidItems.length > 0 && (
        <KnowledgeDialogTable
          caption={tr('invalid_items')}
          columns={[name, { label: tr('failure_reason') }]}
          rows={invalidItems.map((item, index) => ({
            key: index,
            cells: [
              item.name || tr('unnamed'),
              tr(deletionReasons.has(item.reason) ? `reason_${item.reason}` : 'reason_other'),
            ],
          }))}
        />
      )}
    </>
  );
}

export function KnowledgeReferenceTables({
  impact,
  slotCounts,
  page,
  readonly,
  deletingSpace,
  translate: tr,
}: KnowledgeReferenceTablesProps) {
  const sourceLabel = (kind: string) =>
    tr(sourceKinds.has(kind) ? `source_${kind}` : 'source_other');
  const sourceCounts = impact?.source_counts ?? {};
  const restrictedCounts = impact?.restricted_counts ?? {};
  const kinds = Array.from(
    new Set([
      ...Object.keys(sourceCounts),
      ...Object.keys(restrictedCounts),
      ...Object.keys(slotCounts ?? {}),
    ]),
  ).filter(
    (kind) =>
      readonly ||
      ((!deletingSpace || !restrictedDeletionKinds.has(kind)) &&
        (sourceCounts[kind] > 0 || restrictedCounts[kind] > 0)),
  );
  const sourceRows = page?.data ?? [];
  const workflowLocations = Array.from(
    new Set(
      sourceRows.flatMap((row) =>
        row.disclosure.source.source_type === 'workflow_version' ? row.locations ?? [] : [],
      ),
    ),
  );

  return (
    <>
      {kinds.length > 0 && (
        <KnowledgeDialogTable
          caption={tr('references')}
          showCaption={!readonly}
          columns={[
            { label: tr('source_type'), breakLongWords: false },
            { label: tr('source_counts'), numeric: true },
            { label: tr('restricted'), numeric: true },
            ...(slotCounts ? [{ label: tr('slot_counts'), numeric: true }] : []),
          ]}
          rows={kinds.map((kind) => ({
            key: kind,
            cells: [
              sourceLabel(kind),
              sourceCounts[kind] ?? 0,
              restrictedCounts[kind] ?? 0,
              ...(slotCounts ? [slotCounts[kind] ?? 0] : []),
            ],
          }))}
        />
      )}
      {readonly &&
        impact &&
        impact.check_complete !== false &&
        kinds.length === 0 &&
        !sourceRows.length &&
        !page?.has_more && <p className="text-text-2">{tr('no_sources')}</p>}
      {sourceRows.length > 0 && (
        <KnowledgeDialogTable
          caption={tr('source_details')}
          columns={[
            { label: tr('source_name') },
            { label: tr('source_type') },
            { label: tr('source_version') },
            { label: tr('matched_slots'), numeric: true },
          ]}
          rows={sourceRows.map(({ disclosure, matched_slot_count }) => {
            const { entry, source } = disclosure;
            const safe =
              entry &&
              (/^https?:\/\//i.test(entry) || (entry.startsWith('/') && !entry.startsWith('//')));
            const name = disclosure.name || tr('unnamed');
            return {
              key: JSON.stringify([
                source.source_type,
                source.tenant_id,
                source.source_id,
                source.source_version,
              ]),
              cells: [
                safe ? (
                  <a
                    href={entry}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                  >
                    {name}
                  </a>
                ) : (
                  name
                ),
                sourceLabel(source.source_type),
                disclosure.version_label || '—',
                matched_slot_count,
              ],
            };
          })}
        />
      )}
      {workflowLocations.length > 0 && (
        <p>
          {tr('workflow_unlink')} {tr('workflow_locations')}
          {workflowLocations
            .map((code) => tr(locationCodes.has(code) ? `location_${code}` : 'location_workflow_reference'))
            .join(tr('location_separator'))}
        </p>
      )}
    </>
  );
}
