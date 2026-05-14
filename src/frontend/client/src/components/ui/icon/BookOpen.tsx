import React from 'react';

interface FileIconProps {
    className?: string;
}

const BookOpenIcon: React.FC<FileIconProps> = ({ className = '' }) => {
    return (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <path d="M2.91699 15.4167C2.91699 12.207 2.91699 4.58334 2.91699 4.58334C2.91699 3.20263 4.03628 2.08334 5.41699 2.08334H14.5837V12.9167C14.5837 12.9167 7.59724 12.9167 5.41699 12.9167C4.04199 12.9167 2.91699 14.0351 2.91699 15.4167Z" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round"/>
            <path d="M14.5837 12.9167C14.5837 12.9167 5.8977 12.9167 5.41699 12.9167C4.03628 12.9167 2.91699 14.0359 2.91699 15.4167C2.91699 16.7974 4.03628 17.9167 5.41699 17.9167C6.33745 17.9167 10.7819 17.9167 17.0837 17.9167V2.91666" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M5.83301 15.4167H14.1663" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
    );
};

export default BookOpenIcon;
