import type { DeleteImpactSummary } from "~/api/knowledge";

type Localize = (key: string, options?: Record<string, unknown>) => string;

/**
 * Merge several containers' impact summaries into one.
 *
 * A batch delete can span multiple folders, and the user only ever sees a
 * single confirmation, so the numbers have to be added up before they are
 * shown. Samples are capped because the dialog is a sentence, not a list.
 */
export function mergeDeleteImpacts(summaries: DeleteImpactSummary[]): DeleteImpactSummary {
    return summaries.reduce<DeleteImpactSummary>(
        (merged, item) => ({
            rollback_count: merged.rollback_count + item.rollback_count,
            permanent_delete_count: merged.permanent_delete_count + item.permanent_delete_count,
            soft_link_count: merged.soft_link_count + item.soft_link_count,
            share_count: merged.share_count + item.share_count,
            recyclable_count: merged.recyclable_count + item.recyclable_count,
            irreversible: merged.irreversible || item.irreversible,
            rollback_samples: [...merged.rollback_samples, ...item.rollback_samples].slice(0, 5),
        }),
        {
            rollback_count: 0,
            permanent_delete_count: 0,
            soft_link_count: 0,
            share_count: 0,
            recyclable_count: 0,
            irreversible: false,
            rollback_samples: [],
        }
    );
}

/**
 * Describe what a delete will actually do, or null when there is nothing extra to say.
 *
 * Returning null keeps the everyday case untouched: a folder of ordinary files
 * still gets the plain confirmation it always had, and the heavier wording is
 * reserved for deletes that cannot be undone from the recycle bin.
 */
export function buildDeleteImpactDescription(
    summary: DeleteImpactSummary,
    localize: Localize
): string | null {
    if (!summary.irreversible) return null;

    const parts: string[] = [];
    if (summary.rollback_count > 0) {
        parts.push(localize("com_knowledge.delete_impact_rollback", { count: summary.rollback_count }));
    }
    if (summary.permanent_delete_count > 0) {
        parts.push(localize("com_knowledge.delete_impact_permanent", { count: summary.permanent_delete_count }));
    }
    const referenceCount = summary.soft_link_count + summary.share_count;
    if (referenceCount > 0) {
        parts.push(localize("com_knowledge.delete_impact_reference", { count: referenceCount }));
    }
    if (!parts.length) return null;

    return `${parts.join(localize("com_knowledge.delete_impact_separator"))}${localize(
        "com_knowledge.delete_impact_irreversible"
    )}`;
}
