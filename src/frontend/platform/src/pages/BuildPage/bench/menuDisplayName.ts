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
