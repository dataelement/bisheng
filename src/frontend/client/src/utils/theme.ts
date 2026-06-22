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
 * Brand (accent) color theme. Frontend-only for now — persisted in localStorage,
 * applied as a class on <html>. Blue is the default; green re-points the brand
 * CSS variables (see `.theme-green` in style.css).
 */
export type BrandTheme = 'blue' | 'green';

const BRAND_STORAGE_KEY = 'brand-theme';

export const getInitialBrand = (): BrandTheme => {
  if (typeof window === 'undefined' || !window.localStorage) {
    return 'blue';
  }
  try {
    const raw = localStorage.getItem(BRAND_STORAGE_KEY);
    if (raw) {
      const value = JSON.parse(raw);
      if (value === 'green' || value === 'blue') {
        return value;
      }
    }
  } catch {
    // ignore malformed value, fall back to default
  }
  return 'blue';
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
