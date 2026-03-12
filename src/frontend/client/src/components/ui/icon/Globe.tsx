import React from 'react';

interface FileIconProps {
    className?: string;
}

const GlobeIcon: React.FC<FileIconProps> = ({ className = '' }) => {
    return (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <path d="M15.7612 1.66666C17.3452 3.16201 18.3337 5.28136 18.3337 7.63157C18.3337 12.1613 14.6616 15.8333 10.1319 15.8333C7.7817 15.8333 5.66237 14.8448 4.16699 13.2609" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            <path fillRule="evenodd" clipRule="evenodd" d="M10.0003 13.3333C13.222 13.3333 15.8337 10.7217 15.8337 7.49999C15.8337 4.27832 13.222 1.66666 10.0003 1.66666C6.77866 1.66666 4.16699 4.27832 4.16699 7.49999C4.16699 10.7217 6.77866 13.3333 10.0003 13.3333Z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M10 15.8333V18.3333" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M7.5 18.3333H12.5" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
    );
};

export default GlobeIcon;
