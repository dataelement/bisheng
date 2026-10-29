/** Presentation contract only; enterprise authentication remains owned by the host. */
export function isDesktopEmbedded(): boolean {
  const requested = new URLSearchParams(window.location.search).get('embed') === 'dsh';
  try {
    if (requested) window.sessionStorage.setItem('dsh:embedded-chat', 'true');
    return requested || window.sessionStorage.getItem('dsh:embedded-chat') === 'true';
  } catch { return requested; }
}
// Capture the entry URL before the router resolves /workspace to its conversation route.
if (typeof window !== 'undefined') isDesktopEmbedded();
