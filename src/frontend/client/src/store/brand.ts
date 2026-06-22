import { atom } from 'recoil';
import { applyBrandTheme, getInitialBrand, type BrandTheme } from '~/utils/theme';

const BRAND_STORAGE_KEY = 'brand-theme';

/**
 * Brand (accent) color theme — frontend-only switch (blue | green).
 * The atom owns persistence + DOM application so any setter stays in sync:
 * on init it reads localStorage and applies the class, and every change
 * re-persists and re-applies.
 */
const brandTheme = atom<BrandTheme>({
  key: 'brandTheme',
  default: getInitialBrand(),
  effects_UNSTABLE: [
    ({ setSelf, onSet }) => {
      const saved = getInitialBrand();
      setSelf(saved);
      applyBrandTheme(saved);

      onSet((newValue: BrandTheme) => {
        localStorage.setItem(BRAND_STORAGE_KEY, JSON.stringify(newValue));
        applyBrandTheme(newValue);
      });
    },
  ],
});

export default { brandTheme };
