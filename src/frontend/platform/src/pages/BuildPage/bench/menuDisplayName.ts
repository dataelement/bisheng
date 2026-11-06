import i18next from "i18next";

// Workbench menu names share an eight-unit display-width limit.
export const MENU_NAME_MAX_WIDTH = 8;

/** Full-width characters occupying two display units. */
const FULL_WIDTH_RE =
    /[ᄀ-ᅟ⺀-〾ぁ-㏿㐀-䶿一-鿿ꀀ-꓏가-힣豈-﫿︰-﹯＀-｠￠-￦]/;

const charWidth = (char: string): number =>
    // Surrogate pairs also occupy two units.
    char.length > 1 || FULL_WIDTH_RE.test(char) ? 2 : 1;

/** Display width: two units for full-width, one for half-width. */
export const menuNameWidth = (value: string): number =>
    Array.from(value).reduce((sum, char) => sum + charWidth(char), 0);

/** Full-width characters count as two units; keep input intact on overflow. */
export const isMenuNameTooLong = (value: string): boolean =>
    menuNameWidth(value || '') > MENU_NAME_MAX_WIDTH;

/** i18n keys of each module's default menu name (bs namespace) */
export type DefaultMenuNameKey = 'bench.home' | 'bench.knowledgeSpace' | 'bench.subscribe' | 'bench.appCenter';

// Every locale folder platform ships; only the active one is loaded up front.
const MENU_NAME_LANGUAGES = ['zh-Hans', 'en-US', 'ja'];

// Case and spacing don't make a name custom: "apps" / "Knowledge Space" still mean the default.
const comparable = (value: string): string => value.replace(/\s+/g, '').toLowerCase();

/**
 * Value to persist for a menu name. A blank name, or one equal to the module's
 * default name in any shipped language, is stored as '' so the client shows its
 * localized default instead of freezing one language. This also clears names
 * that older versions saved by pre-filling the default.
 */
export async function toStoredMenuName(value: string, defaultKey: DefaultMenuNameKey): Promise<string> {
    const name = (value || '').trim();
    if (!name) return '';
    try {
        await i18next.loadLanguages(MENU_NAME_LANGUAGES);
    } catch {
        // A locale that fails to load just isn't compared; the name is kept as typed.
    }
    const target = comparable(name);
    const isDefault = MENU_NAME_LANGUAGES.some(
        (lng) => comparable(i18next.getFixedT(lng, 'bs')(defaultKey)) === target,
    );
    return isDefault ? '' : name;
}
