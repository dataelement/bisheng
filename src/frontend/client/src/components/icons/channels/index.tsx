import * as React from "react";

export type ChannelIconProps = React.SVGProps<SVGSVGElement>;

export const ChannelBlocksArrowsIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_blocks)">
      <path d="M15 0H1C0.447715 0 0 0.447715 0 1V15C0 15.5523 0.447715 16 1 16H15C15.5523 16 16 15.5523 16 15V1C16 0.447715 15.5523 0 15 0Z" fill="white" fillOpacity="0.01" />
      <path d="M5.66667 2H3C2.44772 2 2 2.44771 2 3V5.66667C2 6.21895 2.44771 6.66667 3 6.66667H5.66667C6.21895 6.66667 6.66667 6.21895 6.66667 5.66667V3C6.66667 2.44772 6.21895 2 5.66667 2Z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.66667 9.3335H3C2.44772 9.3335 2 9.78121 2 10.3335V13.0002C2 13.5524 2.44771 14.0002 3 14.0002H5.66667C6.21895 14.0002 6.66667 13.5524 6.66667 13.0002V10.3335C6.66667 9.78121 6.21895 9.3335 5.66667 9.3335Z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13 2H10.3333C9.78103 2 9.33331 2.44771 9.33331 3V5.66667C9.33331 6.21895 9.78103 6.66667 10.3333 6.66667H13C13.5523 6.66667 14 6.21895 14 5.66667V3C14 2.44772 13.5523 2 13 2Z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 9.3335L9.33333 14.0002M14 9.3335H9.33333H14ZM14 9.3335V14.0002V9.3335Z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_blocks">
        <rect width="16" height="16" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export const ChannelPinIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_pin)">
      <path d="M8.74998 2.625L6.41665 4.95833L4.08331 5.83333L3.20831 6.70833L7.29165 10.7917L8.16665 9.91667L9.04165 7.58333L11.375 5.25" fill="#AEC9FF" />
      <path d="M8.74998 2.625L6.41665 4.95833L4.08331 5.83333L3.20831 6.70833L7.29165 10.7917L8.16665 9.91667L9.04165 7.58333L11.375 5.25" stroke="#5773B4" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.25 8.75L2.625 11.375" stroke="#5773B4" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.45831 2.3335L11.6666 5.54183" stroke="#5773B4" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_pin">
        <rect width="14" height="14" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

/** Gray pin icon used in app plaza card actions */
export const ChannelPinGrayIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_pin_gray)">
      <path d="M8.74998 2.625L6.41665 4.95833L4.08331 5.83333L3.20831 6.70833L7.29165 10.7917L8.16665 9.91667L9.04165 7.58333L11.375 5.25" stroke="#4E5969" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.25 8.75L2.625 11.375" stroke="#4E5969" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.45831 2.3335L11.6666 5.54183" stroke="#4E5969" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_pin_gray">
        <rect width="14" height="14" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

/** Gray "unpin" icon = gray pin + slash */
export const ChannelUnpinGrayIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_unpin_gray)">
      <path d="M8.74998 2.625L6.41665 4.95833L4.08331 5.83333L3.20831 6.70833L7.29165 10.7917L8.16665 9.91667L9.04165 7.58333L11.375 5.25" stroke="#4E5969" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.25 8.75L2.625 11.375" stroke="#4E5969" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.45831 2.3335L11.6666 5.54183" stroke="#4E5969" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2.33331 2.33325L11.6666 11.6666" stroke="#4E5969" strokeWidth="1.16667" strokeLinecap="round" />
    </g>
    <defs>
      <clipPath id="clip0_unpin_gray">
        <rect width="14" height="14" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export const ChannelApplicationIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_app_default)">
      <path d="M7 11.9095C7.61921 12.4638 8.43692 12.8008 9.33333 12.8008C11.2663 12.8008 12.8333 11.2338 12.8333 9.30076C12.8333 7.75469 11.8308 6.44275 10.4404 5.97949" stroke="#818181" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7.92391 8.02112C8.07986 8.41767 8.16552 8.8496 8.16552 9.3015C8.16552 11.2345 6.59852 12.8015 4.66552 12.8015C2.73253 12.8015 1.16553 11.2345 1.16553 9.3015C1.16553 7.75132 2.17336 6.43649 3.56953 5.97656" stroke="#818181" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7 8.13477C8.93299 8.13477 10.5 6.56777 10.5 4.63477C10.5 2.70177 8.93299 1.13477 7 1.13477C5.06701 1.13477 3.5 2.70177 3.5 4.63477C3.5 6.56777 5.06701 8.13477 7 8.13477Z" stroke="#818181" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_app_default">
        <rect width="14" height="14" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export const ChannelAppeffectIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_app_active)">
      <path d="M7 11.9095C7.61921 12.4638 8.43692 12.8008 9.33333 12.8008C11.2663 12.8008 12.8333 11.2338 12.8333 9.30076C12.8333 7.75469 11.8308 6.44275 10.4404 5.97949" stroke="#335CFF" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7.92391 8.02112C8.07986 8.41767 8.16552 8.8496 8.16552 9.3015C8.16552 11.2345 6.59852 12.8015 4.66552 12.8015C2.73253 12.8015 1.16553 11.2345 1.16553 9.3015C1.16553 7.75132 2.17336 6.43649 3.56953 5.97656" stroke="#335CFF" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7 8.13477C8.93299 8.13477 10.5 6.56777 10.5 4.63477C10.5 2.70177 8.93299 1.13477 7 1.13477C5.06701 1.13477 3.5 2.70177 3.5 4.63477C3.5 6.56777 5.06701 8.13477 7 8.13477Z" stroke="#335CFF" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_app_active">
        <rect width="14" height="14" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export const ChannelNotebookOneIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_notebook)">
      <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
      <path d="M2.66699 1.99998C2.66699 1.63179 2.96547 1.33331 3.33366 1.33331H12.667C13.0352 1.33331 13.3337 1.63179 13.3337 1.99998V14C13.3337 14.3682 13.0352 14.6666 12.667 14.6666H3.33366C2.96547 14.6666 2.66699 14.3682 2.66699 14V1.99998Z" stroke="#818181" strokeWidth="1.33333" strokeLinejoin="round" />
      <path d="M5.33301 1.33331V14.6666" stroke="#818181" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 4H10.6667" stroke="#818181" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 6.66669H10.6667" stroke="#818181" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3.33301 1.33331H7.33301" stroke="#818181" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3.33301 14.6667H7.33301" stroke="#818181" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_notebook">
        <rect width="16" height="16" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

/** 与 `public/assets/channel/SingleIconButton.svg` 内芯图形一致（无圆角底框），用于知识空间卡片视图排序按钮 */
export const SingleIconButtonSortGlyph: React.FC<ChannelIconProps> = (props) => (
  <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path
      d="M2 3.8333H9.6667"
      stroke="currentColor"
      strokeWidth="1.33333"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M2 8.1667H9.6667"
      stroke="currentColor"
      strokeWidth="1.33333"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M12 3.8333V12.5L14 10.1667"
      stroke="currentColor"
      strokeWidth="1.33333"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M2 12.5H9.6667"
      stroke="currentColor"
      strokeWidth="1.33333"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const ChannelExchangeFourIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path d="M12.0781 6.61804H3.91993" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M12.0781 6.61898L9.56791 4.10876" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M3.92188 9.38141H12.0801" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M3.92188 9.38041L6.43209 11.8906" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const ChannelSortAmountDownIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path d="M7.66602 2.66666H14.3327" stroke="#999999" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4.66667 13.6667L2 11" stroke="#999999" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4.66602 2.33334V13.6667" stroke="#999999" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7.66602 6H12.9993" stroke="#999999" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7.66602 9.33334H11.666" stroke="#999999" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7.66602 12.6667H10.3327" stroke="#999999" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const ChannelSortAmountUpIcon: React.FC<React.ImgHTMLAttributes<HTMLImageElement>> = ({ className, ...rest }) => (
  <img
    src={`${__APP_ENV__.BASE_URL}/assets/channel/sort-amount-up.svg`}
    alt=""
    width={24}
    height={24}
    className={className}
    {...rest}
  />
);

export const ChannelSortAmountDownBlueIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path d="M7.66602 2.66666H14.3327" stroke="#165DFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4.66667 13.6667L2 11" stroke="#165DFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4.66602 2.33334V13.6667" stroke="#165DFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7.66602 6H12.9993" stroke="#165DFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7.66602 9.33334H11.666" stroke="#165DFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7.66602 12.6667H10.3327" stroke="#165DFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const ChannelSortAmountUpBlueIcon: React.FC<React.ImgHTMLAttributes<HTMLImageElement>> = ({ className, ...rest }) => (
  <img
    src={`${__APP_ENV__.BASE_URL}/assets/channel/sort-amount-up-blue.svg`}
    alt=""
    width={24}
    height={24}
    className={className}
    {...rest}
  />
);

export const ChannelRightSmallUpIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_right_up)">
      <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
      <path d="M5.3335 10.6667L11.0002 5" stroke="#335CFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 5H11V11" stroke="#335CFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_right_up">
        <rect width="16" height="16" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export const ChannelEditIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_edit)">
      <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
      <path d="M2.33334 14H14.3333" stroke="#335CFF" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3.66666 8.90663V11.3333H6.10572L13 4.43603L10.565 2L3.66666 8.90663Z" stroke="#335CFF" strokeWidth="1.33333" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_edit">
        <rect width="16" height="16" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export const ChannelBookIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path d="M96 40.95V96H24V40.95M24 27.45V24H96V27.45" stroke="#4D6DFD" strokeWidth="2.4" />
    <path d="M24 44.3999H96" stroke="#4D6DFD" strokeWidth="2.4" />
    <circle cx="23.9999" cy="34.2001" r="5.1" stroke="#4D6DFD" strokeWidth="1.2" />
    <circle cx="95.9999" cy="34.2001" r="5.1" fill="#4D6DFD" stroke="#4D6DFD" strokeWidth="1.2" />
    <path d="M34.5 34.2002H85.5" stroke="#4D6DFD" strokeWidth="2.4" strokeMiterlimit="4.80973" strokeDasharray="4.8 4.8" />
    <path d="M41.3999 54.6001H78.5999" stroke="#4D6DFD" strokeWidth="1.8" />
    <path d="M41.3999 64.7998H78.5999" stroke="#4D6DFD" strokeWidth="1.8" />
    <path d="M41.3999 75H78.5999" stroke="#4D6DFD" strokeWidth="1.8" />
    <path d="M41.3999 85.2002H78.5999" stroke="#4D6DFD" strokeWidth="1.8" />
  </svg>
);

export const ChannelSuccessIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path d="M3.59998 60H25.102M116.4 60H94.898" stroke="#335CFF" strokeWidth="2.4" strokeDasharray="3 3" />
    <path d="M11.1584 31.8008L25.0831 39.8402M108.845 88.2002L94.9205 80.1608" stroke="#335CFF" strokeWidth="2.4" strokeDasharray="3 3" />
    <path d="M11.1564 88.2002L25.081 80.1608M108.843 31.8007L94.9185 39.8401" stroke="#335CFF" strokeWidth="2.4" strokeDasharray="3 3" />
    <circle cx="60" cy="60.0001" r="23.4" stroke="#335CFF" strokeWidth="2.4" />
    <path d="M47.3274 59.8706L55.8127 68.3559L72.7832 51.3853" stroke="#335CFF" strokeWidth="4.8" strokeLinecap="round" />
    <path d="M22.8209 49.402L24.594 51.1181L27.0436 50.8211L25.3274 52.5942L25.6244 55.0438L23.8514 53.3277L21.4017 53.6246L23.1179 51.8516L22.8209 49.402Z" fill="#335CFF" stroke="#335CFF" strokeWidth="1.2" />
    <path d="M83.9347 89.4143L83.7987 91.8781L85.6273 93.535L83.1635 93.399L81.5066 95.2275L81.6426 92.7637L79.814 91.1068L82.2778 91.2428L83.9347 89.4143Z" fill="#335CFF" stroke="#335CFF" strokeWidth="1.2" />
    <path d="M80.55 17.7002L82.159 22.2412L86.7 23.8502L82.159 25.4592L80.55 30.0002L78.941 25.4592L74.4 23.8502L78.941 22.2412L80.55 17.7002Z" fill="#335CFF" stroke="#335CFF" strokeWidth="1.2" />
  </svg>
);

export const ChannelPlusIcon: React.FC<React.ImgHTMLAttributes<HTMLImageElement>> = (props) => (
  <img
    src={`${__APP_ENV__.BASE_URL}/assets/channel/plus.svg`}
    alt=""
    draggable={false}
    {...props}
  />
);

export const ChannelMinusIcon: React.FC<React.ImgHTMLAttributes<HTMLImageElement>> = (props) => (
  <img
    src={`${__APP_ENV__.BASE_URL}/assets/channel/minus.svg`}
    alt=""
    draggable={false}
    {...props}
  />
);

export const ChannelQuoteIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path d="M12.0002 12C12.2654 12 12.5198 11.8946 12.7073 11.7071C12.8948 11.5196 13.0002 11.2652 13.0002 11V8.558C13.0002 8.29278 12.8948 8.03843 12.7073 7.85089C12.5198 7.66336 12.2654 7.558 12.0002 7.558H10.6122C10.6122 7.20667 10.6328 6.85533 10.6742 6.504C10.7362 6.132 10.8395 5.80133 10.9842 5.512C11.1288 5.22267 11.3152 4.995 11.5432 4.829C11.7698 4.643 12.0592 4.55 12.4112 4.55V3C11.8325 3 11.3258 3.124 10.8912 3.372C10.4595 3.61687 10.0887 3.95595 9.80618 4.364C9.52179 4.81315 9.31239 5.30559 9.18618 5.822C9.05857 6.39174 8.99616 6.97415 9.00018 7.558V11C9.00018 11.2652 9.10554 11.5196 9.29308 11.7071C9.48061 11.8946 9.73497 12 10.0002 12H12.0002ZM6.00018 12C6.2654 12 6.51975 11.8946 6.70729 11.7071C6.89483 11.5196 7.00018 11.2652 7.00018 11V8.558C7.00018 8.29278 6.89483 8.03843 6.70729 7.85089C6.51975 7.66336 6.2654 7.558 6.00018 7.558H4.61218C4.61218 7.20667 4.63285 6.85533 4.67418 6.504C4.73685 6.132 4.84018 5.80133 4.98418 5.512C5.12885 5.22267 5.31518 4.995 5.54318 4.829C5.76985 4.643 6.05918 4.55 6.41118 4.55V3C5.83252 3 5.32585 3.124 4.89118 3.372C4.45952 3.61687 4.08866 3.95595 3.80618 4.364C3.52179 4.81315 3.31239 5.30559 3.18618 5.822C3.05857 6.39174 2.99616 6.97415 3.00018 7.558V11C3.00018 11.2652 3.10554 11.5196 3.29308 11.7071C3.48061 11.8946 3.73497 12 4.00018 12H6.00018Z" fill="#024DE3" />
  </svg>
);

export const ChannelClearIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <g clipPath="url(#clip0_clear)">
      <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
      <path fillRule="evenodd" clipRule="evenodd" d="M6.66663 1.97144H9.33329V4.63812H14.3333V7.30478H1.66663V4.63812H6.66663V1.97144Z" stroke="#818181" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2.66663 13.3333H13.3333V7.33325H2.66663V13.3333Z" stroke="#818181" strokeWidth="1.25" strokeLinejoin="round" />
      <path d="M5.33337 13.2992V11.3047" stroke="#818181" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 13.2991V11.2991" stroke="#818181" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10.6666 13.2992V11.3047" stroke="#818181" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 13.3333H12" stroke="#818181" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_clear">
        <rect width="16" height="16" fill="white" />
      </clipPath>
    </defs>
  </svg>
);

export const ChannelLoadingIcon: React.FC<ChannelIconProps> = (props) => (
  <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
    <path d="M97.5 89.25C97.5 87.554 96.6438 85.8157 94.835 84.1084C93.0237 82.3988 90.338 80.804 86.9199 79.4395C80.0904 76.7129 70.5733 75 60 75C49.4268 75 39.9096 76.713 33.0801 79.4395C29.6621 80.804 26.9763 82.3989 25.165 84.1084C23.3562 85.8157 22.5 87.554 22.5 89.25C22.5001 90.946 23.3563 92.6834 25.165 94.3906C26.9763 96.1003 29.6619 97.6959 33.0801 99.0605C39.9096 101.787 49.4269 103.5 60 103.5C70.5732 103.5 80.0904 101.787 86.9199 99.0605C90.3381 97.6959 93.0237 96.1003 94.835 94.3906C96.6436 92.6834 97.4999 90.9459 97.5 89.25ZM99.8994 89.25C99.8993 91.8203 98.5902 94.1473 96.4824 96.1367C94.3771 98.1239 91.3947 99.8578 87.8096 101.289C80.6325 104.154 70.7999 105.899 60 105.899C49.2 105.899 39.3665 104.154 32.1895 101.289C28.6046 99.8579 25.6228 98.1237 23.5176 96.1367C21.4098 94.1473 20.0997 91.8203 20.0996 89.25C20.0996 86.6796 21.4098 84.3528 23.5176 82.3633C25.6228 80.3762 28.6046 78.6422 32.1895 77.2109C39.3665 74.3457 49.2 72.5996 60 72.5996C70.8 72.5996 80.6325 74.3457 87.8096 77.2109C91.3948 78.6422 94.3771 80.3761 96.4824 82.3633C98.5902 84.3528 99.8994 86.6797 99.8994 89.25Z" fill="#4D6DFD" />
    <path d="M60.0002 80.7002C70.0352 80.7002 78.8029 82.3365 84.807 84.7335C87.8284 85.9397 89.8098 87.2036 90.9227 88.2541C91.5157 88.8138 91.5157 89.6866 90.9227 90.2463C89.8098 91.2968 87.8284 92.5607 84.807 93.7669C78.8029 96.1639 70.0352 97.8002 60.0002 97.8002C49.9652 97.8002 41.1975 96.1639 35.1933 93.7669C32.172 92.5607 30.1906 91.2968 29.0776 90.2463C28.4845 89.6865 28.4845 88.8139 29.0776 88.2541C30.1906 87.2036 32.172 85.9397 35.1933 84.7335C41.1975 82.3365 49.9652 80.7002 60.0002 80.7002Z" fill="#4D6DFD" />
    <path d="M60.0008 79.5C70.1491 79.5 79.0748 81.1528 85.2527 83.6191C88.3574 84.8586 90.4869 86.1926 91.7469 87.3818C92.8414 88.4151 92.8415 90.0859 91.7469 91.1191C90.4869 92.3084 88.3574 93.6424 85.2527 94.8818C79.0748 97.3482 70.1491 99 60.0008 99C49.8525 99 40.9267 97.3482 34.7488 94.8818C31.6442 93.6424 29.5147 92.3083 28.2547 91.1191C27.1599 90.0858 27.1599 88.4152 28.2547 87.3818C29.5147 86.1926 31.6441 84.8586 34.7488 83.6191C40.9267 81.1528 49.8524 79.5 60.0008 79.5ZM60.0008 81.9004C50.0791 81.9004 41.4689 83.52 35.6385 85.8477C32.7008 87.0205 30.8681 88.2153 29.9021 89.127C29.8388 89.1867 29.8338 89.2319 29.8338 89.25C29.8338 89.268 29.8386 89.314 29.9021 89.374C30.8681 90.2856 32.7012 91.4797 35.6385 92.6523C41.4689 94.98 50.0791 96.6006 60.0008 96.6006C69.9224 96.6006 78.5327 94.98 84.3631 92.6523C87.3004 91.4796 89.1335 90.2856 90.0994 89.374C90.1629 89.3141 90.1678 89.2682 90.1678 89.25C90.1677 89.2317 90.1626 89.1866 90.0994 89.127C89.1335 88.2153 87.3008 87.0205 84.3631 85.8477C78.5327 83.52 69.9224 81.9004 60.0008 81.9004Z" fill="#4D6DFD" />
    <path d="M30 25.5V89.0996H27.5996V25.5H30ZM92.3994 25.5V89.0996H90V25.5H92.3994Z" fill="#4D6DFD" />
    <path d="M74.0293 43.1143L72 44.2861L69.9717 43.1143L71.1719 41.0361L72 41.5146L72.8291 41.0361L74.0293 43.1143ZM67.4844 37.9502V38.9062L68.3135 39.3857L67.1133 41.4648L65.085 40.293V37.9502H67.4844ZM78.916 37.9502V40.293L76.8877 41.4648L75.6875 39.3857L76.5166 38.9062V37.9502H78.916ZM67.7139 32.1748L68.3135 33.2148L67.4844 33.6924V34.6504H65.085V32.3076L67.1133 31.1357L67.7139 32.1748ZM78.916 32.3076V34.6504H76.5166V33.6924L75.6875 33.2148L76.2871 32.1748L76.8877 31.1357L78.916 32.3076ZM74.0293 29.4863L72.8291 31.5645L72 31.085L71.1719 31.5645L69.9717 29.4863L72 28.3145L74.0293 29.4863Z" fill="#4D6DFD" />
    <path d="M54.6152 49.4072V57.3926L47.6992 61.3857L40.7842 57.3926V49.4072L47.6992 45.4141L54.6152 49.4072ZM43.1836 50.792V56.0059L47.6992 58.6143L52.2158 56.0059V50.792L47.6992 48.1846L43.1836 50.792Z" fill="#4D6DFD" />
    <path d="M71.9999 67.2002L77.7157 70.5002V77.1002L71.9999 80.4002L66.2842 77.1002V70.5002L71.9999 67.2002Z" fill="#4D6DFD" />
    <path d="M78.916 69.8076V77.793L72 81.7861L65.085 77.793V69.8076L72 65.8145L78.916 69.8076ZM67.4844 71.1924V76.4062L72 79.0146L76.5166 76.4062V71.1924L72 68.585L67.4844 71.1924Z" fill="#4D6DFD" />
  </svg>
);

