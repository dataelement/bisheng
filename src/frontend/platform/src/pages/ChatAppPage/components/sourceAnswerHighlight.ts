function escapeHtml(value: string): string {
    return value.replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[character]!);
}

/** Only generated spans are markup; answer and keyword bytes always remain text. */
export function highlightSourceAnswer(message: string, keywords: readonly string[]): string {
    const literals = [...new Set(keywords.filter(keyword => keyword.length > 0))]
        .sort((left, right) => right.length - left.length)
        .map(keyword => keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (!literals.length) return escapeHtml(message);
    const pattern = new RegExp(`(${literals.join('|')})`, 'g');
    return message.split(pattern).map((part, index) =>
        index % 2 === 1 ? `<span>${escapeHtml(part)}</span>` : escapeHtml(part),
    ).join('');
}
