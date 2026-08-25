import { useTranslation } from 'react-i18next';
import type { ResolvedImage } from './types';

interface ImageGalleryProps {
  items: ResolvedImage[];
  /** Optional caption, used when the gallery sits below a rendered table. */
  title?: string;
}

/**
 * Pictures that cannot live inside a cell: sheets holding nothing but a drawing
 * (report exporters do this), and pictures anchored outside the used range.
 * They keep their authored size instead of being squeezed into a table cell.
 */
export function ImageGallery({ items, title }: ImageGalleryProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.excelPreview' });

  if (items.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      {title ? <div className="text-xs font-medium text-gray-500">{title}</div> : null}
      {items.map(({ image, anchor }, index) => (
        <img
          key={`${image.id}-${index}`}
          src={`data:${image.mimeType};base64,${image.base64}`}
          alt={`${t('imageRef')} ${index + 1}`}
          className="h-auto max-w-full object-contain"
          style={{ width: anchor.sizePx ? `${anchor.sizePx.w}px` : undefined }}
        />
      ))}
    </div>
  );
}
