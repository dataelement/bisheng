import React from 'react';

interface BookPlusIconProps {
    className?: string;
}

const BookPlusIcon: React.FC<BookPlusIconProps> = ({ className = '' }) => {
    return (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
            <path d="M1.24072 13.2658C2.26825 12.6725 3.43382 12.3602 4.6203 12.3602C5.80678 12.3602 6.97236 12.6725 7.99988 13.2658C8.59162 12.9241 9.22913 12.6757 9.89006 12.5264" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M1.24072 3.50248C2.26825 2.90924 3.43382 2.59692 4.6203 2.59692C5.80678 2.59692 6.97236 2.90924 7.99988 3.50248C9.02741 2.90924 10.193 2.59692 11.3795 2.59692C12.5659 2.59692 13.7315 2.90924 14.759 3.50248" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M1.24072 3.50256V13.2658" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M8 3.50256V13.2658" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M14.7593 3.50256V8.00867" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M13.3365 9.26575L13.3365 13.2657" stroke="currentColor" strokeLinecap="round"/>
            <path d="M11.3365 11.2657H15.3365" stroke="currentColor" strokeLinecap="round"/>
        </svg>
    );
};

export default BookPlusIcon;
