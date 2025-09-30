import axios from 'axios';
import React from 'react';

export { default as buildDefaultConvo } from './buildDefaultConvo';
export { default as buildTree } from './buildTree';
export { default as cleanupPreset } from './cleanupPreset';
export { default as cn } from './cn';
export * from './convos';
export * from './endpoints';
export * from './files';
export * from './forms';
export { default as getDefaultEndpoint } from './getDefaultEndpoint';
export { default as getLoginError } from './getLoginError';
export * from './json';
export * from './languages';
export * from './latex';
export * from './localStorage';
export { default as logger } from './logger';
export * from './map';
export * from './messages';
export * from './presets';
export * from './promptGroups';
export * from './prompts';
export * from './textarea';
export * from './theme';

export const languages = [
  'java',
  'c',
  'markdown',
  'css',
  'html',
  'xml',
  'bash',
  'json',
  'yaml',
  'jsx',
  'python',
  'c++',
  'javascript',
  'csharp',
  'php',
  'typescript',
  'swift',
  'objectivec',
  'sql',
  'r',
  'kotlin',
  'ruby',
  'go',
  'x86asm',
  'matlab',
  'perl',
  'pascal',
];

export const removeFocusOutlines = '';
export const removeFocusRings =
  'focus:outline-none focus:ring-0 focus:ring-opacity-0 focus:ring-offset-0';

export const cardStyle =
  'transition-colors rounded-md min-w-[75px] border font-normal bg-white hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-700 dark:bg-gray-800 text-black dark:text-gray-600 focus:outline-none data-[state=open]:bg-gray-50 dark:data-[state=open]:bg-gray-700';

export const defaultTextProps =
  'rounded-md border border-gray-200 focus:border-gray-400 focus:bg-gray-50 bg-transparent text-sm shadow-[0_0_10px_rgba(0,0,0,0.05)] outline-none focus-within:placeholder:text-text-primary focus:placeholder:text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-gray-400 focus:ring-opacity-20 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gray-700 dark:border-gray-600 dark:focus:bg-gray-600 dark:focus:border-gray-600 dark:text-gray-50 dark:shadow-[0_0_15px_rgba(0,0,0,0.10)] dark:focus:outline-none';

export const optionText =
  'p-0 shadow-none text-right pr-1 h-8 border-transparent hover:bg-gray-800/10 dark:hover:bg-white/10 dark:focus:bg-white/10 transition-colors';

export const defaultTextPropsLabel =
  'rounded-md border border-gray-300 bg-transparent text-sm shadow-[0_0_10px_rgba(0,0,0,0.10)] outline-none focus-within:placeholder:text-text-primary focus:placeholder:text-text-primary placeholder:text-text-secondary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-700 dark:bg-gray-700 dark:text-gray-50 dark:shadow-[0_0_15px_rgba(0,0,0,0.10)] dark:focus:border-gray-600 dark:focus:outline-none';

export function capitalizeFirstLetter(string: string) {
  return string.charAt(0).toUpperCase() + string.slice(1);
}

export const handleDoubleClick: React.MouseEventHandler<HTMLElement> = (event) => {
  const range = document.createRange();
  range.selectNodeContents(event.target as Node);
  const selection = window.getSelection();
  if (!selection) {
    return;
  }
  selection.removeAllRanges();
  selection.addRange(range);
};

export const extractContent = (
  children: React.ReactNode | { props: { children: React.ReactNode } } | string,
): string => {
  if (typeof children === 'string') {
    return children;
  }
  if (React.isValidElement(children)) {
    return extractContent((children.props as { children?: React.ReactNode }).children);
  }
  if (Array.isArray(children)) {
    return children.map(extractContent).join('');
  }
  return '';
};

export const normalizeLayout = (layout: number[]) => {
  const sum = layout.reduce((acc, size) => acc + size, 0);
  if (Math.abs(sum - 100) < 0.01) {
    return layout.map((size) => Number(size.toFixed(2)));
  }

  const factor = 100 / sum;
  const normalizedLayout = layout.map((size) => Number((size * factor).toFixed(2)));

  const adjustedSum = normalizedLayout.reduce(
    (acc, size, index) => (index === layout.length - 1 ? acc : acc + size),
    0,
  );
  normalizedLayout[normalizedLayout.length - 1] = Number((100 - adjustedSum).toFixed(2));

  return normalizedLayout;
};

// ding
export const playDing = () => {
  // 1. 创建音频元素
  const audio = new Audio(__APP_ENV__.BASE_URL + '/assets/ding.wav');
  audio.volume = 0.5; // 50%音量

  // 2. 播放音频
  audio.play().catch(error => {
    console.error('播放失败:', error);
    audio.remove(); // 如果播放失败也移除元素
  });

  // 3. 播放结束后销毁
  audio.addEventListener('ended', () => {
    console.log('播放结束，销毁音频元素');
    audio.remove();
  });

  // 4. 错误处理（网络问题等）
  audio.addEventListener('error', () => {
    console.error('音频加载失败');
    audio.remove();
  });
}


/**
 * 切换导航栏的展开/闭合状态
 * @param {boolean} shouldExpand - true表示展开，false表示关闭
 */
export const toggleNav = (shouldExpand) => {
  return // 去掉自动收起展开
  // 获取导航栏切换按钮元素
  const navToggle = document.querySelector('div[id="toggle-left-nav"]');

  if (!navToggle) {
    console.error('未找到导航栏切换按钮');
    return;
  }

  // 获取当前展开状态
  const isExpanded = navToggle.getAttribute('aria-expanded') === 'true';

  // 判断是否需要操作
  if ((shouldExpand && !isExpanded) || (!shouldExpand && isExpanded)) {
    // 触发点击事件来切换状态
    navToggle.click();
  }
}

/**
 * 时间字符串格式化函数
 * @param {string} time - 时间字符串，格式为 "YYYY-mm-ddTHH:MM:SS"
 * @param {boolean} hideTime - 是否隐藏时分秒
 * @return {string} 格式化后的时间字符串，格式为 "YYYY-mm-dd HH:MM:SS"
 */
export const formatTime = (time: string, hideTime: boolean = false) => {
  const value = time.replace('T', ' ').replaceAll('-', '/');
  return hideTime ? value.slice(0, -3) : value
}

// Date转换为目标格式
export function formatDate(date: Date, format: string): string {
  const addZero = (num) => num < 10 ? `0${num}` : `${num}`
  const replacements = {
    'yyyy': date.getFullYear(),
    'MM': addZero(date.getMonth() + 1),
    'dd': addZero(date.getDate()),
    'HH': addZero(date.getHours()),
    'mm': addZero(date.getMinutes()),
    'ss': addZero(date.getSeconds())
  }
  return format.replace(/yyyy|MM|dd|HH|mm|ss/g, (match) => replacements[match])
}

// param time: yyyy-mm-ddTxxxx
export function formatStrTime(time: string, notSameDayFormat: string): string {
  if (!time) return ''
  const date1 = new Date(time)
  const date2 = new Date()
  return date1.getFullYear() === date2.getFullYear() &&
    date1.getMonth() === date2.getMonth() &&
    date1.getDate() === date2.getDate() ? formatDate(date1, 'HH:mm') : formatDate(date1, notSameDayFormat)
}

const copyTextInDom = (dom) => {
  const range = document.createRange();

  range.selectNode(dom);
  window.getSelection().removeAllRanges();
  window.getSelection().addRange(range);

  return new Promise((res) => {
    document.execCommand('copy');
    window.getSelection().removeAllRanges();
    res(dom.innerText);
  })
}

// 复制到剪切板
export const copyText = (text: string | HTMLElement) => {
  // 复制 dom 内文本
  if (typeof text !== 'string') return copyTextInDom(text)
  // 高级 API直接复制文本（需要 https 环境）
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text)
  }
  // 通过把文本写入 dom, 间接通过选中 dom 复制文本
  const areaDom = document.createElement("textarea");
  // 设置样式使其不在屏幕上显示
  areaDom.style.position = 'absolute';
  areaDom.style.left = '-9999px';
  areaDom.value = text;
  document.body.appendChild(areaDom);

  return copyTextInDom(areaDom).then((str) => {
    document.body.removeChild(areaDom);
  })
};


export function downloadFile(url, label) {
  console.log('download file :>> ', url);

  return axios.get(url, { responseType: "blob" }).then((res: any) => {
    const blob = new Blob([res.data]);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = label;
    link.click();
    URL.revokeObjectURL(link.href);
  }).catch(console.error);
}


// uuid
export const generateUUID = (length: number) => {
  let d = new Date().getTime()
  const uuid = ''.padStart(length, 'x').replace(/[xy]/g, (c) => {
    const r = (d + Math.random() * 16) % 16 | 0
    d = Math.floor(d / 16)
    return (c == 'x' ? r : (r & 0x7 | 0x8)).toString(16)
  })
  return uuid
}


// 取后缀名
export function getFileExtension(filename) {
  if (!filename) return '';
  const basename = filename.split(/[\\/]/).pop(); // 去除路径
  if (!basename) return '';
  const match = basename.match(/\.([^.]+)$/);
  return (match ? match[1] : '').toUpperCase();
}