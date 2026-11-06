interface NumericDraftBounds {
    min?: number;
    max?: number;
    maxLength?: number;
}

// Drafts may be cleared while editing; business submission still checks required values.
export function isNumberDraftWithinBounds(value: string, { min = 0, max, maxLength }: NumericDraftBounds = {}): boolean {
    if (value === '') return true;
    const number = Number(value);
    return Number.isFinite(number) && number >= min && (max === undefined || number <= max)
        && (maxLength === undefined || value.length <= maxLength);
}
