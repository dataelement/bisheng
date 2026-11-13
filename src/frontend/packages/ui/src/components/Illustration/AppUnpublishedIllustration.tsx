import { useId } from 'react';
import type { IllustrationProps } from './index';

export function AppUnpublishedIllustration({ className, grey, style, ...props }: IllustrationProps) {
    const id = `app-unpublished-${useId()}`;
    const badgeId = `${id}-badge`;
    const badgeMaskId = `${id}-badge-mask`;
    const leftPlugId = `${id}-left-plug`;
    const leftPlugMaskId = `${id}-left-plug-mask`;
    const rightPlugId = `${id}-right-plug`;
    const rightPlugMaskId = `${id}-right-plug-mask`;

    return (
        <svg
            width="400"
            height="400"
            viewBox="0 0 400 400"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className={['brand-illustration', grey && 'illus-grey', className].filter(Boolean).join(' ')}
            {...props}
            style={{ color: 'rgb(var(--bg-page))', ...style }}
        >
            <defs>
                <path id={badgeId} d="M115.162 321.178C146.732 321.178 172.324 295.586 172.324 264.016C172.324 232.446 146.732 206.854 115.162 206.854C83.5923 206.854 58 232.446 58 264.016C58 295.586 83.5923 321.178 115.162 321.178Z" />
                <path id={leftPlugId} d="M80.8648 252.583H96.4544V283.763H80.8648C75.6682 283.763 72.5503 279.606 72.5503 274.409V261.937C72.5503 256.741 75.6682 252.583 80.8648 252.583Z" />
                <path id={rightPlugId} d="M136.988 242.19H148.42C153.617 242.19 156.735 246.348 156.735 251.544V264.016C156.735 269.212 153.617 273.37 148.42 273.37H136.988V242.19Z" />
                <mask id={badgeMaskId} maskUnits="userSpaceOnUse" x="50" y="198.854" width="130" height="130">
                    <rect fill="white" x="50" y="198.854" width="130" height="130" />
                    <use href={`#${badgeId}`} fill="black" />
                </mask>
                <mask id={leftPlugMaskId}>
                    <use href={`#${leftPlugId}`} fill="white" />
                </mask>
                <mask id={rightPlugMaskId}>
                    <use href={`#${rightPlugId}`} fill="white" />
                </mask>
            </defs>
            <path d="M220.22 301.608L297.849 256.904C301.299 255.185 303.024 251.746 303.024 248.307V158.899L225.395 203.603C222.414 205.221 222.377 205.221 220.182 206.333L220.22 301.608ZM308.199 131.389C316.825 136.547 322 145.144 322 153.741V248.307C322 258.623 316.825 267.22 308.199 270.659L225.395 317.082C216.769 322.24 206.419 322.24 199.518 317.082L116.714 270.659C108.088 265.501 102.913 256.904 102.913 248.307V153.741C102.913 143.425 108.088 134.828 116.714 131.389L199.518 84.9659C208.144 79.8077 218.494 79.8077 225.395 84.9659L308.199 131.389Z" style={{ fill: 'rgb(var(--illus-100))' }} />
            <use href={`#${badgeId}`} style={{ fill: 'rgb(var(--illus-500))' }} />
            <use href={`#${badgeId}`} strokeWidth="14.5503" stroke="currentColor" mask={`url(#${badgeMaskId})`} />
            <path d="M67.354 268.173H79.8257" strokeWidth="8.31448" strokeLinecap="round" stroke="currentColor" />
            <use href={`#${leftPlugId}`} fill="currentColor" />
            <use href={`#${leftPlugId}`} strokeWidth="2.07862" stroke="currentColor" mask={`url(#${leftPlugMaskId})`} />
            <path d="M96.4546 259.859H104.769M96.4546 276.488H104.769" strokeWidth="5.19655" strokeLinecap="round" stroke="currentColor" />
            <path d="M152.577 257.78H164.01" strokeWidth="8.31448" strokeLinecap="round" stroke="currentColor" />
            <use href={`#${rightPlugId}`} fill="currentColor" />
            <use href={`#${rightPlugId}`} strokeWidth="2.07862" stroke="currentColor" mask={`url(#${rightPlugMaskId})`} />
            <path d="M128.673 249.466H136.987M128.673 266.095H136.987" strokeWidth="5.19655" strokeLinecap="round" stroke="currentColor" />
            <path d="M116.201 230.758V238.033" strokeWidth="8.31448" strokeLinecap="round" stroke="currentColor" />
            <path d="M115.162 291.558V298.833" strokeWidth="8.31448" strokeLinecap="round" stroke="currentColor" />
        </svg>
    );
}
