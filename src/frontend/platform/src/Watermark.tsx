import React, { useEffect } from 'react';
// import md5 from 'js-md5';
import { formatDate } from './util/utils';

function fnv1aHash(input) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
  }
  return (hash >>> 0).toString(16); // 转换为16进制字符串
}

const Watermark = ({ text = "水印文字", opacity = 0.38 }) => {
  useEffect(() => {
    // 加密
    const date = formatDate(new Date(), 'yyyy-MM-dd');
    const date2 = formatDate(new Date(), 'yyyyMMdd');
    const _md5 = fnv1aHash(`${date}&%${text}`)
    const watermarkText = _md5 + '-' + text + '-' + date2;
    const fontSize = 18;  // 设置字体大小
    const width = 700;    // 水印图案的宽度
    const height = 500;   // 水印图案的高度

    // 创建水印元素
    const watermarkDiv = document.createElement('div');
    watermarkDiv.classList.add('watermark');
    // watermarkDiv.innerText = watermarkText;
    watermarkDiv.style.opacity = opacity;
    document.body.appendChild(watermarkDiv);

    // 动态调整水印图案的大小
    const style = document.createElement('style');
    style.innerHTML = `
      .watermark {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 1000;
        user-select: none;
        pointer-events: none;
        display: flex;
        justify-content: center;
        align-items: center;
        opacity: ${opacity};
        transform-origin: top left;
        background: url('data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"%3E%3Ctext x="0" y="${height / 2}" transform="rotate(-30)" font-size="${fontSize}" fill="rgba(0,0,0,0.2)"%3E${watermarkText}%3C/text%3E%3C/svg%3E') repeat;
        background-size: ${width}px ${height}px;
      }
    `;
    document.head.appendChild(style);

    // 清理函数，移除水印
    return () => {
      document.head.removeChild(style);
      document.body.removeChild(watermarkDiv);
    };
  }, [text, opacity]); // 依赖项是 text 和 opacity，确保当这些值变化时，水印会更新

  return null;
};

export default Watermark;
