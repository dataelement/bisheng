type Rgb = readonly [number, number, number];

function parseLegacyPrimary(value: string): Rgb | undefined {
    const match = /^(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%$/.exec(value);
    if (!match) return;
    const hue = ((Number(match[1]) % 360) + 360) % 360;
    const saturation = Number(match[2]) / 100;
    const lightness = Number(match[3]) / 100;
    if (!Number.isFinite(hue) || saturation > 1 || lightness > 1) return;
    const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
    const intermediate = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
    const offset = lightness - chroma / 2;
    const sectors: Rgb[] = [
        [chroma, intermediate, 0], [intermediate, chroma, 0], [0, chroma, intermediate],
        [0, intermediate, chroma], [intermediate, 0, chroma], [chroma, 0, intermediate],
    ];
    const sector = sectors[Math.floor(hue / 60)];
    const channel = (index: number) => Math.round((sector[index] + offset) * 255);
    return [channel(0), channel(1), channel(2)];
}

function mix(color: Rgb, target: Rgb, amount: number): string {
    return color.map((channel, index) => Math.round(channel * (1 - amount) + target[index] * amount)).join(' ');
}

function brandPalette(primary: Rgb, dark: boolean): Record<string, string> {
    const white: Rgb = [255, 255, 255];
    const black: Rgb = [0, 0, 0];
    const tintTarget = dark ? black : white;
    const strongTarget = dark ? white : black;
    const tintAmounts = dark ? [0.85, 0.70, 0.55, 0.35, 0.12] : [0.92, 0.76, 0.60, 0.40, 0.20];
    const strongAmounts = dark ? [0.20, 0.40, 0.60, 0.80] : [0.12, 0.30, 0.50, 0.70];
    const palette: Record<string, string> = {};
    [50, 100, 200, 300, 400].forEach((step, index) => {
        palette[`--brand-${step}`] = mix(primary, tintTarget, tintAmounts[index]);
    });
    [600, 700, 800, 900].forEach((step, index) => {
        palette[`--brand-${step}`] = mix(primary, strongTarget, strongAmounts[index]);
    });
    palette['--brand-500'] = palette['--brand-main'] = primary.join(' ');
    palette['--brand-muted'] = mix(primary, [128, 128, 128], 0.55);
    return palette;
}

/**
 * Adapt saved platform HSL colors to the shared RGB-channel token contract.
 * The legacy bootstrap fetch and theme editor both write --primary inline;
 * observing that source handles initial load, late fetches, and live edits
 * without adding a second persistence path or modifying shared components.
 * Only the brand ramp is themed: danger, neutral, and disabled colors stay
 * owned by the shared library. Without a valid custom primary, use its CSS.
 */
export function installPlatformThemeBridge(root: HTMLElement = document.documentElement) {
    let signature: string | undefined;
    const previous = new Map<string, { value: string; priority: string }>();
    const restore = () => {
        previous.forEach(({ value, priority }, key) => {
            if (value) root.style.setProperty(key, value, priority);
            else root.style.removeProperty(key);
        });
        previous.clear();
    };
    const sync = () => {
        const primary = root.style.getPropertyValue('--primary').trim();
        const dark = root.classList.contains('dark');
        const nextSignature = `${primary}:${dark}`;
        // Our own token writes also mutate `style`. Ignore them instead of
        // recursively observing and rewriting the same palette forever.
        if (signature === nextSignature) return;
        signature = nextSignature;
        const color = parseLegacyPrimary(primary);
        if (!color) {
            restore();
            return;
        }
        Object.entries(brandPalette(color, dark)).forEach(([key, value]) => {
            if (!previous.has(key)) previous.set(key, {
                value: root.style.getPropertyValue(key), priority: root.style.getPropertyPriority(key),
            });
            root.style.setProperty(key, value);
        });
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ['style', 'class'] });
    return () => {
        observer.disconnect();
        restore();
    };
}
