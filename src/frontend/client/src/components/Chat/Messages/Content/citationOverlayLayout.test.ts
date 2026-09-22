/**
 * How the references list and a cited document share the right edge.
 *
 * Both are fixed to that edge at the same width, so the document used to land
 * underneath the very list that opened it and the click looked like a no-op.
 */
import {
  resolveCitationOverlayLayout,
  CITATION_REFERENCES_PAIRED_WIDTH_PX,
} from './citationUtils';

const WIDE = { canPair: true };
const NARROW = { canPair: false };

describe('citation overlay layout', () => {
  it('keeps the list beside the document when there is room for both', () => {
    const layout = resolveCitationOverlayLayout({ referencesOpen: true, documentOpen: true, ...WIDE });

    expect(layout.showReferencesPanel).toBe(true);
    expect(layout.documentRightOffsetPx).toBe(CITATION_REFERENCES_PAIRED_WIDTH_PX);
  });

  it('narrows the list to an index once a document sits next to it', () => {
    const alone = resolveCitationOverlayLayout({ referencesOpen: true, documentOpen: false, ...WIDE });
    const paired = resolveCitationOverlayLayout({ referencesOpen: true, documentOpen: true, ...WIDE });

    expect(alone.referencesWidthClass).not.toEqual(paired.referencesWidthClass);
    expect(paired.referencesWidthClass).toContain('360px');
  });

  it('steps the list aside when the screen cannot hold both', () => {
    const layout = resolveCitationOverlayLayout({ referencesOpen: true, documentOpen: true, ...NARROW });

    expect(layout.showReferencesPanel).toBe(false);
    // Nothing to sit beside, so the document keeps the edge it always had.
    expect(layout.documentRightOffsetPx).toBeNull();
  });

  it('brings the list back once the document is closed', () => {
    const layout = resolveCitationOverlayLayout({ referencesOpen: true, documentOpen: false, ...NARROW });

    expect(layout.showReferencesPanel).toBe(true);
  });

  it('leaves the document on the edge when it was opened without the list', () => {
    const layout = resolveCitationOverlayLayout({ referencesOpen: false, documentOpen: true, ...WIDE });

    expect(layout.showReferencesPanel).toBe(false);
    expect(layout.documentRightOffsetPx).toBeNull();
  });
});
