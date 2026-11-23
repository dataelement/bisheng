export const appCardSurfaceClassName = [
  'rounded-xl border-[0.5px] border-solid border-border-base p-2',
  '[--app-card-surface:var(--bg-page)] dark:[--app-card-surface:var(--fill-1)]',
  'bg-[rgb(var(--app-card-surface))]',
  'bg-[linear-gradient(135deg,rgb(var(--brand-500)/0.04)_0%,rgb(var(--app-card-surface))_50%,rgb(var(--brand-500)/0.04)_100%)]',
  'dark:bg-[linear-gradient(135deg,rgb(var(--brand-500)/0.08)_0%,rgb(var(--app-card-surface))_50%,rgb(var(--brand-500)/0.08)_100%)]',
].join(' ');
