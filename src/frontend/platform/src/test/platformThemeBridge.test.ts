import { afterEach, describe, expect, it } from 'vitest';
import { installPlatformThemeBridge } from '@/utils/platformThemeBridge';

const root = document.documentElement;
let stop: (() => void) | undefined;
afterEach(() => {
    stop?.();
    root.removeAttribute('style');
    root.classList.remove('dark');
});

describe('platform theme compatibility', () => {
    it('maps an existing primary color without replacing the legacy variable', () => {
        root.style.setProperty('--primary', '0 100% 50%');
        stop = installPlatformThemeBridge(root);
        expect(root.style.getPropertyValue('--primary')).toBe('0 100% 50%');
        expect(root.style.getPropertyValue('--brand-main')).toBe('255 0 0');
        expect(root.style.getPropertyValue('--brand-500')).toBe('255 0 0');
        expect(root.style.getPropertyValue('--brand-400')).toBe('255 51 51');
        expect(root.style.getPropertyValue('--brand-600')).toBe('224 0 0');
        expect(root.style.getPropertyValue('--danger')).toBe('');
    });

    it('picks up theme configuration that arrives after the app starts', async () => {
        stop = installPlatformThemeBridge(root);
        expect(root.style.getPropertyValue('--brand-main')).toBe('');
        root.style.setProperty('--primary', '120 100% 25%');
        await Promise.resolve();
        expect(root.style.getPropertyValue('--brand-main')).toBe('0 128 0');
        root.style.setProperty('--primary', '240 100% 50%');
        await Promise.resolve();
        expect(root.style.getPropertyValue('--brand-main')).toBe('0 0 255');
    });

    it('reverses state brightness in dark mode while retaining the chosen main color', async () => {
        root.style.setProperty('--primary', '0 100% 50%');
        stop = installPlatformThemeBridge(root);
        root.classList.add('dark');
        await Promise.resolve();
        expect(root.style.getPropertyValue('--brand-main')).toBe('255 0 0');
        expect(root.style.getPropertyValue('--brand-400')).toBe('224 0 0');
        expect(root.style.getPropertyValue('--brand-600')).toBe('255 51 51');
    });

    it('releases mapped tokens when the custom color is removed or invalid', async () => {
        root.style.setProperty('--primary', '0 100% 50%');
        stop = installPlatformThemeBridge(root);
        root.style.removeProperty('--primary');
        await Promise.resolve();
        expect(root.style.getPropertyValue('--brand-main')).toBe('');
        expect(root.style.getPropertyValue('--brand-400')).toBe('');
        root.style.setProperty('--primary', 'invalid-color');
        await Promise.resolve();
        expect(root.style.getPropertyValue('--brand-main')).toBe('');
    });
});
