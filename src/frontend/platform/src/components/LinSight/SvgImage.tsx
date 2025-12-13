import { useState, useEffect } from 'react';
import { FileIcon } from '../bs-icons/file';

interface SvgImageProps {
  fileUrl: string;
  alt: string;
  className?: string;
}

export const SvgImage = ({ fileUrl, alt, className = "" }: SvgImageProps) => {
  const [svgContent, setSvgContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const fullUrl = `${__APP_ENV__.BASE_URL}${fileUrl}`;

  // Core: Add width: 100% and height: auto styles to the SVG to maintain responsive aspect ratio
  const addSvgResponsiveStyles = (svgText: string) => {
    const svgRegex = /<svg([^>]*?)>/i; // Match the root SVG element
    return svgText.replace(
      svgRegex,
      (match, attributes) => {
        // Target style: width 100%, height auto
        const targetStyles = 'width: 100%; height: auto;';

        if (attributes.includes('style=')) {
          // If there's an existing style attribute, merge the styles (avoiding duplicates)
          return `<svg${attributes.replace(
            /style=(["'])(.*?)\1/,
            (styleMatch, quote, styles) => {
              // Remove existing width and height styles
              const filteredStyles = styles
                .split(';')
                .filter(style =>
                  !style.trim().startsWith('width:') &&
                  !style.trim().startsWith('height:')
                )
                .join(';');
              // Append the new styles
              const newStyles = filteredStyles
                ? `${filteredStyles}; ${targetStyles}`
                : targetStyles;
              return `style=${quote}${newStyles}${quote}`;
            }
          )}>`;
        } else {
          // If no style attribute, directly add the styles
          return `<svg${attributes} style="${targetStyles}">`;
        }
      }
    );
  };

  useEffect(() => {
    const abortController = new AbortController();

    const fetchSvg = async () => {
      try {
        setLoading(true);
        setError(false);

        const response = await fetch(fullUrl, {
          signal: abortController.signal,
          headers: { 'Accept': 'image/svg+xml, text/plain' }
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const text = await response.text();
        // Process SVG text, adding responsive styles
        const processedSvg = addSvgResponsiveStyles(text);
        setSvgContent(processedSvg);
      } catch (err) {
        if (!abortController.signal.aborted) {
          setError(true);
          console.error('SVG load failed:', err);
        }
      } finally {
        if (!abortController.signal.aborted) setLoading(false);
      }
    };

    fetchSvg();
    return () => abortController.abort();
  }, [fullUrl]);

  if (loading) {
    return (
      <div className={`flex items-center justify-center ${className}`}>
        <FileIcon type="svg" className="size-10 opacity-50 animate-pulse" />
      </div>
    );
  }

  if (error || !svgContent) {
    return (
      <div className={`flex flex-col items-center justify-center ${className}`}>
        <FileIcon type="svg" className="size-10 text-gray-400" />
      </div>
    );
  }

  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: svgContent }}
    />
  );
};
