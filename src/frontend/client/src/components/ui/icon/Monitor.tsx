import React from 'react';

interface FileIconProps {
    className?: string;
}

const MonitorIcon: React.FC<FileIconProps> = ({ className = '' }) => {
    return (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <g clipPath="url(#clip0_1658_18338)">
                <path d="M10 13.3333H3.33333C2.8731 13.3333 2.5 12.9602 2.5 12.5V4.16665C2.5 3.70641 2.8731 3.33331 3.33333 3.33331H16.6667C17.1269 3.33331 17.5 3.70641 17.5 4.16665V8.33331" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M5.83301 16.6667H9.99967" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M7.5 13.3333V16.6666" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M7.5 10V6.66669" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M10 10V9.16669" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M12.5 9.99998V8.33331" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M10 10V9.16669" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M17.915 12.4993H12.4984" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M17.915 12.4993L16.2484 10.8326" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M12.5 15.0007H17.9167" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M12.5 15.0007L14.1667 16.6674" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            </g>
            <defs>
                <clipPath id="clip0_1658_18338">
                    <rect width="20" height="20" fill="white"/>
                </clipPath>
            </defs>
        </svg>

    );
};

export default MonitorIcon;
