import type { AppConversation, ConversationGroup } from '~/@types/app';
import { dateKeys } from '~/utils/convos';

/**
 * Group conversations by time dimension.
 * Group labels are i18n keys (com_ui_date_*); pass through localize() when rendering.
 * Years use numeric string labels (e.g. "2024").
 */
export function groupConversationsByTime(
  conversations: AppConversation[],
): ConversationGroup[] {
  const now = new Date();
  const todayStart = startOfDay(now);
  const yesterdayStart = startOfDay(addDays(todayStart, -1));
  const past7Start = startOfDay(addDays(todayStart, -6));
  const past30Start = startOfDay(addDays(todayStart, -29));

  const buckets: Record<string, AppConversation[]> = {};
  const yearBuckets: Record<string, AppConversation[]> = {};

  // Sort by updatedAt desc (backend should already do this, but be safe)
  const sorted = [...conversations].sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  );

  for (const conv of sorted) {
    const d = new Date(conv.updatedAt);

    if (d >= todayStart) {
      (buckets[dateKeys.today] ??= []).push(conv);
    } else if (d >= yesterdayStart) {
      (buckets[dateKeys.yesterday] ??= []).push(conv);
    } else if (d >= past7Start) {
      (buckets[dateKeys.previous7Days] ??= []).push(conv);
    } else if (d >= past30Start) {
      (buckets[dateKeys.previous30Days] ??= []).push(conv);
    } else {
      const year = String(d.getFullYear());
      (yearBuckets[year] ??= []).push(conv);
    }
  }

  const orderedLabels = [
    dateKeys.today,
    dateKeys.yesterday,
    dateKeys.previous7Days,
    dateKeys.previous30Days,
  ];
  const result: ConversationGroup[] = orderedLabels
    .filter((label) => buckets[label]?.length)
    .map((label) => ({ label, conversations: buckets[label] }));

  // Append year groups sorted descending
  Object.keys(yearBuckets)
    .sort((a, b) => Number(b) - Number(a))
    .forEach((year) => {
      result.push({ label: year, conversations: yearBuckets[year] });
    });

  return result;
}

/**
 * Build a shareable app URL (no backend call needed).
 * Format: /share/app_{appId}_{flowType}
 */
export function getAppShareUrl(appId: string, flowType: number | string): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- global env constant
  const baseUrl = __APP_ENV__.BASE_URL || '';
  return `${window.location.origin}${baseUrl}/share/app_${appId}_${flowType}`;
}

// ---- helpers ----

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function addDays(date: Date, days: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}
