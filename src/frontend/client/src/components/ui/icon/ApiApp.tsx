import React from 'react';

interface ApiAppIconProps {
    className?: string;
}

const ApiAppIcon: React.FC<ApiAppIconProps> = ({ className = '' }) => {
    return (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <path d="M6 7.97905V3.33331C6 2.22874 6.89543 1.33331 8 1.33331C9.10457 1.33331 10 2.22874 10 3.33331V4.00188" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round"/>
            <path d="M10 8.00116V12.6667C10 13.7712 9.10457 14.6667 8 14.6667C6.89543 14.6667 6 13.7712 6 12.6667V11.99" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round"/>
            <path d="M8.00065 10H3.3287C2.22705 10 1.33398 9.10457 1.33398 8C1.33398 6.89543 2.22705 6 3.3287 6H3.99685" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round"/>
            <path d="M8 6H12.6629C13.7696 6 14.6667 6.89543 14.6667 8C14.6667 9.10457 13.7696 10 12.6629 10H12.0221" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round"/>
        </svg>
    );
};

export default ApiAppIcon;
