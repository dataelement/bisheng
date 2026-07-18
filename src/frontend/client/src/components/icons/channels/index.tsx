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
      <path d="M2.33334 14H14.3333" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3.66666 8.90663V11.3333H6.10572L13 4.43603L10.565 2L3.66666 8.90663Z" stroke="currentColor" strokeWidth="1.33333" strokeLinejoin="round" />
    </g>
    <defs>
      <clipPath id="clip0_edit">
        <rect width="16" height="16" fill="white" />
      </clipPath>
    </defs>
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


