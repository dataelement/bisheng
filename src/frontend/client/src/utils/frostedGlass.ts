/**
 * Global switch for frosted-glass (`backdrop-filter`) surfaces.
 *
 * Frosted glass is banned by default (root AGENTS.md §4): each such element is
 * its own compositing layer that re-snapshots and re-blurs its backdrop every
 * frame, and on machines without GPU acceleration (信创 / 信保安全浏览器) that runs
 * on the CPU and stalls scrolling. The design spec allows one exception — a
 * full-screen overlay of which at most one exists at a time — and every such
 * use goes through this flag so a deployment can turn them all off at once.
 *
 * Usage: `cn(FROSTED_GLASS_ENABLED && FROSTED_GLASS_CLASS)` on the overlay.
 * The blur itself is defined once, in `style.css` under `.bs-frosted-glass`.
 *
 * Off switch (build-time): `VITE_FROSTED_GLASS=false`. Default is on.
 */
export const FROSTED_GLASS_ENABLED = import.meta.env.VITE_FROSTED_GLASS !== "false";

/** The only class that carries `backdrop-filter`; see `style.css`. */
export const FROSTED_GLASS_CLASS = "bs-frosted-glass";
