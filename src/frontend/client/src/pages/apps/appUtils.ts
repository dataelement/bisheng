import type { AppConversation, ConversationGroup } from '~/@types/app';

/**
 * Group conversations by time dimension.
 * Groups: 今天 / 昨天 / 过去 7 天 / 过去 30 天 / {Year}
 *
 * - "过去 7 天" excludes today and yesterday
 * - "过去 30 天" excludes the past 7 days
 * - Year groups for anything older than 30 days
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
      (buckets['今天'] ??= []).push(conv);
    } else if (d >= yesterdayStart) {
      (buckets['昨天'] ??= []).push(conv);
    } else if (d >= past7Start) {
      (buckets['过去 7 天'] ??= []).push(conv);
    } else if (d >= past30Start) {
      (buckets['过去 30 天'] ??= []).push(conv);
    } else {
      const year = String(d.getFullYear());
      (yearBuckets[year] ??= []).push(conv);
    }
  }

  // Ordered output: 今天 → 昨天 → 过去 7 天 → 过去 30 天 → years desc
  const orderedLabels = ['今天', '昨天', '过去 7 天', '过去 30 天'];
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
  const baseUrl = (window as any).__APP_ENV__?.BASE_URL ?? '';
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
