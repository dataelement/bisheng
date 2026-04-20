import React from 'react';

interface FileIconProps {
    className?: string;
}

const TodayItemIcon: React.FC<FileIconProps> = ({ className = '' }) => {
    return (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <path d="M5 10C5 8.34315 6.34315 7 8 7H16C17.6569 7 19 8.34315 19 10V14C19 15.6569 17.6569 17 16 17H9.5694C9.19495 17 8.82563 17.0872 8.49071 17.2546L6.78885 18.1056C5.96699 18.5165 5 17.9189 5 17V10Z" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
            <circle cx="15" cy="12" r="0.75" fill="currentColor"/>
            <circle cx="12" cy="12" r="0.75" fill="currentColor"/>
            <circle cx="9" cy="12" r="0.75" fill="currentColor"/>
        </svg>
    );
};

export default TodayItemIcon;
