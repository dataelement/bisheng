import { useMemo } from "react";
import { cn } from "~/utils"

const gradients = [
    'bg-amber-500',
    'bg-orange-600',
    'bg-teal-500',
    'bg-purple-600',
    'bg-blue-700'
]

export default function AppAvator({ id = 1, flowType = '', url = '', className = '' }) {

    const color = useMemo(() => {
        const str = id + ''
        let hex = '';
        for (let i = 0; i < str.length; i++) {
            hex += str.charCodeAt(i).toString(16);
        }
        const num = parseInt(hex, 16) || 0;
        return gradients[parseInt(num + '', 16) % gradients.length]
    }, [id])

    if (url) return <img src={url} className={cn(`w-6 h-6 rounded-sm object-cover`, className)} />

    const flowIcons = {
        1: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <g id="Group 628">
                <g id="Group 625">
                    <ellipse id="Ellipse 17" cx="13.0622" cy="13.4282" rx="6" ry="3" transform="rotate(-30 13.0622 13.4282)"
                        stroke="url(#paint0_linear_410_134)" stroke-width="2" />
                    <ellipse id="Ellipse 18" cx="11.0622" cy="9.9641" rx="7" ry="4" transform="rotate(-30 11.0622 9.9641)"
                        fill="url(#paint1_linear_410_134)" />
                </g>
            </g>
            <defs>
                <linearGradient id="paint0_linear_410_134" x1="13.0622" y1="9.42815" x2="13.0622" y2="17.4282"
                    gradientUnits="userSpaceOnUse">
                    <stop stop-color="white" stop-opacity="0.1" />
                    <stop offset="1" stop-color="white" />
                </linearGradient>
                <linearGradient id="paint1_linear_410_134" x1="11.0622" y1="5.9641" x2="11.0622" y2="13.9641"
                    gradientUnits="userSpaceOnUse">
                    <stop stop-color="white" stop-opacity="0.82" />
                    <stop offset="1" stop-color="white" />
                </linearGradient>
            </defs>
        </svg>,
        5: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="8" y="7" width="8" height="2" rx="1" fill="white" />
            <rect x="5" y="11" width="14" height="2" rx="1" fill="white" />
            <rect x="8" y="15" width="8" height="2" rx="1" fill="white" />
        </svg>,
        10: <svg viewBox="-400 -400 1800 1800" version="1.1" xmlns="http://www.w3.org/2000/svg"
            p-id="6880" width="24" height="24">
            <path
                d="M982.646154 208.738462c-41.353846-80.738462-145.723077-230.4-338.707692-141.784616-120.123077 55.138462-187.076923 86.646154-187.076924 86.646154l-173.292307 74.830769c-49.230769 23.630769-155.569231-9.846154-216.615385-31.507692-17.723077-5.907692-33.476923 11.815385-25.6 29.538461 41.353846 80.738462 145.723077 230.4 338.707692 141.784616 120.123077-55.138462 360.369231-159.507692 360.369231-159.507692 49.230769-23.630769 155.569231 9.846154 216.615385 31.507692 17.723077 3.938462 33.476923-13.784615 25.6-31.507692zM567.138462 460.8c-21.661538 11.815385-108.307692 51.2-108.307693 51.2l-86.646154 37.415385c-43.323077 23.630769-135.876923-7.876923-191.015384-29.538462-15.753846-7.876923-29.538462 11.815385-21.661539 27.569231 35.446154 78.769231 128 220.553846 297.353846 133.907692 106.338462-53.169231 194.953846-88.615385 194.953847-88.615384 43.323077-23.630769 135.876923 7.876923 191.015384 29.538461 15.753846 5.907692 29.538462-11.815385 21.661539-29.538461-35.446154-76.8-128-218.584615-297.353846-131.938462z m-63.015385 348.553846c-17.723077 9.846154-47.261538 27.569231-47.261539 27.569231-33.476923 21.661538-102.4-5.907692-143.753846-25.6-11.815385-5.907692-21.661538 11.815385-15.753846 27.569231 25.6 70.892308 94.523077 198.892308 222.523077 120.123077 47.261538-29.538462 47.261538-27.569231 47.261539-27.569231 35.446154-17.723077 102.4 5.907692 143.753846 25.6 11.815385 5.907692 21.661538-11.815385 15.753846-27.569231-25.6-70.892308-90.584615-192.984615-222.523077-120.123077z"
                fill="#FFFFFF" p-id="6881"></path>
        </svg>
    }

    return <div className={cn(`size-5 min-w-5 rounded-md flex justify-center items-center`, color, className)}>
        {flowIcons[flowType]}
    </div>
};
