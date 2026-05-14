import React from 'react';

interface FileIconProps {
    className?: string;
}

const LingsiIcon: React.FC<FileIconProps> = ({ className = '' }) => {
    return (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <path d="M9.50358 17.5395C11.2519 17.8829 14.9601 17.7461 15.4996 15C16.1871 11.5 10.0701 11.5545 8.49958 13.3869C6.92907 15.2194 14.2958 16.3126 17.295 13.3868C20.1369 10.6144 17.9641 6.94717 11.917 6.75378" stroke="#6B778D" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M7.73161 5.28968C7.81263 4.89331 8.37898 4.89331 8.45999 5.28968C8.63893 6.16513 9.32308 6.84928 10.1985 7.02821C10.5949 7.10923 10.5949 7.67558 10.1985 7.75659C9.32308 7.93553 8.63893 8.61968 8.45999 9.49512C8.37898 9.8915 7.81263 9.8915 7.73161 9.49512C7.55268 8.61968 6.86853 7.93553 5.99308 7.75659C5.59671 7.67558 5.59671 7.10923 5.99308 7.02821C6.86853 6.84928 7.55268 6.16513 7.73161 5.28968Z" fill="url(#paint0_linear_lingsi)"/>
            <path d="M5.88608 9.2002C5.02818 9.9921 3.95742 11.6677 6.17476 13.4099" stroke="#6B778D" strokeLinecap="round" strokeLinejoin="round"/>
            <defs>
                <linearGradient id="paint0_linear_lingsi" x1="8.0958" y1="4.9924" x2="8.0958" y2="9.7924" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#0084FF"/>
                    <stop offset="1" stopColor="#00B2FF"/>
                </linearGradient>
            </defs>
        </svg>
    );
};

export default LingsiIcon;
