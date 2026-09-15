const BLOCK_TAGS = new Set([
    'p',
    'div',
    'li',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'tr',
    'pre',
    'blockquote',
]);

const HTML_PRETTY_PRINT = /^[\n\r\t]+$/;

/**
 * Convert clipboard HTML into markup safe to insert into the prompt editor.
 * Preserves variable badges, turns <br> / block tags into line breaks, and
 * strips wrapper newlines that browsers add around the copied fragment.
 */
export function htmlClipboardToInsertable(root: ParentNode): string {
    const text = walkClipboardNode(root).replace(/^\n+|\n+$/g, '');
    return text.replace(/\n/g, '<br>');
}

function walkClipboardNode(node: ParentNode): string {
    let result = '';

    node.childNodes.forEach((child) => {
        if (child.nodeType === Node.TEXT_NODE) {
            const text = child.textContent ?? '';
            if (HTML_PRETTY_PRINT.test(text)) {
                return;
            }
            result += text;
            return;
        }

        if (child.nodeType !== Node.ELEMENT_NODE) {
            return;
        }

        const el = child as Element;
        const tag = el.tagName.toLowerCase();

        if (tag === 'span' && el.classList.contains('textarea-badge')) {
            result += el.outerHTML;
            return;
        }

        if (tag === 'br') {
            result += '\n';
            return;
        }

        const inner = walkClipboardNode(el);
        result += inner;
        if (BLOCK_TAGS.has(tag) && inner && !result.endsWith('\n')) {
            result += '\n';
        }
    });

    return result;
}
