import React from 'react';

export const AiChatIcon = ({ className, stroke = "#335CFF", ...props }: React.SVGProps<SVGSVGElement> & { stroke?: string }) => (
    <svg className={className} width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
        <path d="M11.3652 4.08326C11.9421 4.94661 12.25 5.96165 12.25 7V12.25H7C5.96165 12.25 4.94661 11.9421 4.08326 11.3652C3.2199 10.7883 2.54699 9.9684 2.14963 9.00909C1.75227 8.04978 1.6483 6.99418 1.85088 5.97578C2.05345 4.95738 2.55346 4.02191 3.28769 3.28769C4.02191 2.55346 4.95738 2.05345 5.97578 1.85088C6.99418 1.6483 8.04978 1.75227 9.00909 2.14963C9.9684 2.54699 10.7883 3.2199 11.3652 4.08326Z" stroke={stroke} strokeWidth="0.7" />
        <circle cx="5.42529" cy="7.17499" r="0.875" stroke={stroke} strokeWidth="0.7" />
        <circle cx="7.17529" cy="7.17499" r="0.875" stroke={stroke} strokeWidth="0.7" />
        <circle cx="8.92529" cy="7.17499" r="0.875" stroke={stroke} strokeWidth="0.7" />
    </svg>
);
