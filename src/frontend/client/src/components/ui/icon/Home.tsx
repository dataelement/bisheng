import React from 'react';

interface FileIconProps {
    className?: string;
}

const HomeIcon: React.FC<FileIconProps> = ({ className = '' }) => {
    return (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <g clipPath="url(#clip0_1658_18324)">
                <path d="M20 0H0V20H20V0Z" fill="white" fillOpacity="0.01"/>
                <path d="M3.75033 17.5V7.5L1.66699 9.16667L10.0003 2.5L18.3337 9.16667L16.2503 7.5V17.5H3.75033Z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M7.91699 12.0833V17.5H12.0837V12.0833H7.91699Z" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round"/>
                <path d="M3.75 17.5H16.25" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round"/>
            </g>
            <defs>
                <clipPath id="clip0_1658_18324">
                    <rect width="20" height="20" fill="white"/>
                </clipPath>
            </defs>
        </svg>
    );
};

export default HomeIcon;
