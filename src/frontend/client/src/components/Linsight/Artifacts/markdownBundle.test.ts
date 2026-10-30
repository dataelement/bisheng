/**
 * A markdown deliverable goes out as a zip only when it references a local
 * (workspace) image; remote and inline images keep the single-file download.
 */
import { hasLocalImageRefs } from './markdownBundle';

jest.mock('~/api/linsight', () => ({ getMdBundle: jest.fn() }));
jest.mock('./artifactUtils', () => ({ fetchArtifactBlob: jest.fn() }));

describe('hasLocalImageRefs', () => {
    it('detects markdown and html images by workspace path', () => {
        expect(hasLocalImageRefs('![curve](output/charts/curve.png)')).toBe(true);
        expect(hasLocalImageRefs('![a](/output/a.png "title")')).toBe(true);
        expect(hasLocalImageRefs('<img width="300" src="charts/a.png">')).toBe(true);
    });

    it('ignores remote and inline images and plain links', () => {
        expect(hasLocalImageRefs('![a](https://example.com/a.png)')).toBe(false);
        expect(hasLocalImageRefs('![a](data:image/png;base64,AAAA)')).toBe(false);
        expect(hasLocalImageRefs('[report](output/report.md)')).toBe(false);
        expect(hasLocalImageRefs('# plain')).toBe(false);
    });
});
