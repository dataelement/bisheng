import { atom } from 'recoil';
import { applyBrandTheme, getInitialBrand, type BrandTheme } from '~/utils/theme';

/**
 * Workbench accent theme (blue | green). Admin-configured and delivered via
 * window.BRAND_CONFIG.workbenchTheme; brand-runtime.js applies the class before
 * paint. This atom just mirrors that value into React state and re-applies on
 * set — no per-user localStorage persistence (source of truth = backend brand
 * config).
 */
const brandTheme = atom<BrandTheme>({
  key: 'brandTheme',
  default: getInitialBrand(),
  effects_UNSTABLE: [
    ({ setSelf, onSet }) => {
      const initial = getInitialBrand();
      setSelf(initial);
      applyBrandTheme(initial);

      onSet((newValue: BrandTheme) => {
        applyBrandTheme(newValue);
      });
    },
  ],
});

export default { brandTheme };
