export const applyFontSize = (val: string) => {
  const root = document.documentElement;
  const size = val.split('-')[1]; // This will be 'xs', 'sm', 'base', 'lg', or 'xl'

  switch (size) {
    case 'xs':
      root.style.setProperty('--markdown-font-size', '0.75rem'); // 12px
      break;
    case 'sm':
      root.style.setProperty('--markdown-font-size', '0.875rem'); // 14px
      break;
    case 'base':
      root.style.setProperty('--markdown-font-size', '1rem'); // 16px
      break;
    case 'lg':
      root.style.setProperty('--markdown-font-size', '1.125rem'); // 18px
      break;
    case 'xl':
      root.style.setProperty('--markdown-font-size', '1.25rem'); // 20px
      break;
  }
};

/**
 * Brand (accent) color theme. Admin-configured "workbench theme" delivered via
 * window.BRAND_CONFIG.workbenchTheme (applied by brand-runtime.js before paint).
 * Blue is the default; green re-points the brand CSS variables incl. --primary
 * (see `.theme-green` in style.css). No longer a per-user localStorage switch.
 */
export type BrandTheme = 'blue' | 'green';

export const getInitialBrand = (): BrandTheme => {
  if (typeof window === 'undefined') return 'blue';
  return window.BRAND_CONFIG?.workbenchTheme === 'green' ? 'green' : 'blue';
};

export const applyBrandTheme = (brand: BrandTheme) => {
  if (typeof document === 'undefined') return;
  document.documentElement.classList.toggle('theme-green', brand === 'green');
};

export const getInitialTheme = () => {
  if (typeof window !== 'undefined' && window.localStorage) {
    // const storedPrefs = window.localStorage.getItem('color-theme') || 'light';
    const storedPrefs = 'light';
    if (typeof storedPrefs === 'string') {
      return storedPrefs;
    }

    const userMedia = window.matchMedia('(prefers-color-scheme: light)');
    if (userMedia.matches) {
      return 'light';
    }
  }

  return 'light'; // light theme as the default;
};
