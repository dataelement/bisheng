export interface SentComposerReference {
    kind: 'skill' | 'tool' | 'space';
    label: string;
    /** UTF-16 offset in the trimmed prompt. */
    offset: number;
    /** Present on a knowledge-space tag. Space names may also start with '#'. */
    is_tag?: true;
}

export interface ComposerReference extends Omit<SentComposerReference, 'offset'> {
    key: string;
}
