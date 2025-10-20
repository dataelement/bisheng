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

  // 核心：给SVG添加 width:100% 和 height:auto 样式，保持比例自适应
  const addSvgResponsiveStyles = (svgText: string) => {
    const svgRegex = /<svg([^>]*?)>/i; // 匹配SVG根节点
    return svgText.replace(
      svgRegex,
      (match, attributes) => {
        // 目标样式：宽度100%，高度自适应
        const targetStyles = 'width: 100%; height: auto;';
        
        if (attributes.includes('style=')) {
          // 已有style属性，合并样式（去重）
          return `<svg${attributes.replace(
            /style=(["'])(.*?)\1/,
            (styleMatch, quote, styles) => {
              // 过滤掉已有的width和height样式
              const filteredStyles = styles
                .split(';')
                .filter(style => 
                  !style.trim().startsWith('width:') && 
                  !style.trim().startsWith('height:')
                )
                .join(';');
              // 拼接新样式
              const newStyles = filteredStyles 
                ? `${filteredStyles}; ${targetStyles}` 
                : targetStyles;
              return `style=${quote}${newStyles}${quote}`;
            }
          )}>`;
        } else {
          // 无style属性，直接添加
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
        // 处理SVG文本，添加响应式样式
        const processedSvg = addSvgResponsiveStyles(text);
        setSvgContent(processedSvg);
      } catch (err) {
        if (!abortController.signal.aborted) {
          setError(true);
          console.error('SVG加载失败:', err);
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