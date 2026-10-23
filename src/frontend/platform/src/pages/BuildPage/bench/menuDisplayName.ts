import i18next from "i18next";

// 工作台四个模块的「菜单显示名称」共用长度规则。
// 客户端侧边栏只有 64px 宽、10px 字号，所以按显示宽度而不是字符数来限：
// 全角(CJK / 全角标点 / emoji)计 2 个单位，半角计 1 个，上限 8 个单位
// —— 中文、日文最多 4 个字，英文最多 8 个字母。
export const MENU_NAME_MAX_WIDTH = 8;

/** 需要占两个半角位的字符区间：CJK、假名、谚文、全角标点、以及代理对（emoji） */
const FULL_WIDTH_RE =
    /[ᄀ-ᅟ⺀-〾ぁ-㏿㐀-䶿一-鿿ꀀ-꓏가-힣豈-﫿︰-﹯＀-｠￠-￦]/;

const charWidth = (char: string): number =>
    // 代理对（emoji 等）用 char.length > 1 判断，正则区间覆盖不到 BMP 之外
    char.length > 1 || FULL_WIDTH_RE.test(char) ? 2 : 1;

/** 名称的显示宽度（全角 2 / 半角 1） */
export const menuNameWidth = (value: string): number =>
    Array.from(value).reduce((sum, char) => sum + charWidth(char), 0);

/** 超出上限的部分直接截掉，输入时即时生效，无需再报“太长”的错 */
export const clampMenuName = (value: string): string => {
    let width = 0;
    let result = '';
    for (const char of Array.from(value)) {
        const next = width + charWidth(char);
        if (next > MENU_NAME_MAX_WIDTH) break;
        width = next;
        result += char;
    }
    return result;
};

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
