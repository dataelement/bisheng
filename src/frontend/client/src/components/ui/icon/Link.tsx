import React from 'react';

interface FileIconProps {
    className?: string;
}

const LinkIcon: React.FC<FileIconProps> = ({ className = '' }) => {
    return (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <path d="M3.53894 4.8468C3.87682 4.85587 4.21126 4.87877 4.54171 4.91495C10.5005 5.56746 15.1604 10.5389 15.3241 16.6319" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M11.5449 16.8771C11.5449 12.3209 7.85148 8.62749 3.29536 8.62749" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M7.85589 17.0283C7.85589 14.4247 5.74536 12.3142 3.14185 12.3142" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
            <path fillRule="evenodd" clipRule="evenodd" d="M3.23511 16.9363C3.6419 17.3431 4.30146 17.3431 4.70825 16.9363C5.11504 16.5295 5.11504 15.8699 4.70825 15.4631C4.30146 15.0563 3.6419 15.0563 3.23511 15.4631C2.82832 15.8699 2.82832 16.5295 3.23511 16.9363Z" fill="currentColor"/>
        </svg>
    );
};

export default LinkIcon;
