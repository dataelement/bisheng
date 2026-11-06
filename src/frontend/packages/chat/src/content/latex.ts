const containsLatexRegex = /\\\(.*?\\\)|\\\[.*?\\\]|\$.*?\$|\\begin\{equation\}.*?\\end\{equation\}/;
const inlineLatex = new RegExp(/\\\((.+?)\\\)/, 'g');
const blockLatex = new RegExp(/\\\[(.*?[^\\])\\\]/, 'gs');
const restoreCodeBlocks = (content: string, codeBlocks: string[]) => {
    return content.replace(/<<CODE_BLOCK_(\d+)>>/g, (match, index) => codeBlocks[index]);
};
const codeBlockRegex = /(```[\s\S]*?```|`.*?`)/g;
export const processLaTeX = (_content: string) => {
    let content = _content;
    const codeBlocks: string[] = [];
    let index = 0;
    content = content.replace(codeBlockRegex, (match) => {
        codeBlocks[index] = match;
        return `<<CODE_BLOCK_${index++}>>`;
    });
    let processedContent = content.replace(/(\$)(?=\s?\d)/g, '\\$');
    if (!containsLatexRegex.test(processedContent)) {
        return restoreCodeBlocks(processedContent, codeBlocks);
    }
    processedContent = processedContent
        .replace(inlineLatex, (match: string, equation: string) => `$${equation}$`)
        .replace(blockLatex, (match: string, equation: string) => `$$${equation}$$`);
    return restoreCodeBlocks(processedContent, codeBlocks);
};
export function preprocessLaTeX(content: string): string {
    const codeBlocks: string[] = [];
    content = content.replace(/(```[\s\S]*?```|`[^`\n]+`)/g, (match, code) => {
        codeBlocks.push(code);
        return `<<CODE_BLOCK_${codeBlocks.length - 1}>>`;
    });
    const latexExpressions: string[] = [];
    content = content.replace(/(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\(.*?\\\))/g, (match) => {
        latexExpressions.push(match);
        return `<<LATEX_${latexExpressions.length - 1}>>`;
    });
    content = content.replace(/\$(?=\d)/g, '\\$');
    content = content.replace(/<<LATEX_(\d+)>>/g, (_, index) => latexExpressions[parseInt(index)]);
    content = content.replace(/<<CODE_BLOCK_(\d+)>>/g, (_, index) => codeBlocks[parseInt(index)]);
    content = escapeBrackets(content);
    content = escapeMhchem(content);
    return content;
}
export function escapeBrackets(text: string): string {
    const pattern = /(```[\S\s]*?```|`.*?`)|\\\[([\S\s]*?[^\\])\\]|\\\((.*?)\\\)/g;
    return text.replace(pattern, (match: string, codeBlock: string | undefined, squareBracket: string | undefined, roundBracket: string | undefined): string => {
        if (codeBlock != null) {
            return codeBlock;
        }
        else if (squareBracket != null) {
            return `$$${squareBracket}$$`;
        }
        else if (roundBracket != null) {
            return `$${roundBracket}$`;
        }
        return match;
    });
}
export function escapeMhchem(text: string) {
    return text.replaceAll('$\\ce{', '$\\\\ce{').replaceAll('$\\pu{', '$\\\\pu{');
}
