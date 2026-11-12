import { unzipSync, zipSync, strFromU8, strToU8 } from 'fflate';
import { JSDOM } from 'jsdom';

const PRESENTATION = 'http://schemas.openxmlformats.org/presentationml/2006/main';
/** Select visible slides from our checked, exported template. Retain the whole
 * package's font/glyph and resource context so each Office job sees the same
 * inputs as a complete export. Relationships and editable slide parts stay intact.
 */
export function createOfficePreviewBatches(bytes, pageCount) {
  const entries = unzipSync(bytes);
  const xml = entries['ppt/presentation.xml'];
  if (!xml || !Number.isInteger(pageCount) || pageCount < 1 || pageCount > 200)
    throw new Error('Office preview requires a valid exported presentation');
  const window = new JSDOM('').window;
  try {
    const document = new window.DOMParser().parseFromString(strFromU8(xml), 'application/xml');
    const list = document.getElementsByTagNameNS(PRESENTATION, 'sldIdLst')[0];
    const slides = list ? [...list.children] : [];
    if (document.getElementsByTagName('parsererror').length || slides.length !== pageCount
      || slides.some(slide => slide.namespaceURI !== PRESENTATION || slide.localName !== 'sldId'))
      throw new Error('Office preview slide list mismatch');
    const startNumber = Number(document.documentElement.getAttribute('firstSlideNum') ?? 1);
    if (!Number.isSafeInteger(startNumber)) throw new Error('Office preview slide numbering is invalid');
    const serializer = new window.XMLSerializer();
    return (first, count) => {
      if (!Number.isInteger(first) || !Number.isInteger(count) || first < 0 || count < 1 || first + count > pageCount)
        throw new Error('Office preview batch range is invalid');
      const selected = document.cloneNode(true);
      const selectedList = selected.getElementsByTagNameNS(PRESENTATION, 'sldIdLst')[0];
      [...selectedList.children].forEach((slide, index) => {
        if (index < first || index >= first + count) slide.remove();
      });
      selected.documentElement.setAttribute('firstSlideNum', String(startNumber + first));
      const parts = { ...entries, 'ppt/presentation.xml': strToU8(serializer.serializeToString(selected)) };
      return zipSync(Object.fromEntries(Object.entries(parts).map(([name, value]) => [name,
        /\.(png|jpe?g|gif|webp)$/iu.test(name) ? [value, { level: 0 }] : value])), { level: 6 });
    };
  } finally { window.close(); }
}
