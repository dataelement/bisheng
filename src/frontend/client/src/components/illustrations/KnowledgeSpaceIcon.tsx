import React, { useId, useMemo } from "react";
import { useRecoilValue } from "recoil";
import store from "~/store";

/**
 * Knowledge-space card icon (mobile full-page list row).
 *
 * Designer asset: a stack of document-preview cards behind a folder. The folder
 * gradient and the foreground file emblem follow the blue ⇄ green brand theme —
 * and they are genuinely *different drawings* per theme (blue = text document,
 * green = spreadsheet) with bespoke gradients that don't map onto the `--brand-*`
 * palette. So instead of recolouring one geometry, we render the active theme's
 * full tree (BRAND-THEME-HANDOFF.md §3 covers why SVG can't just use `var()`).
 *
 * The two faint card previews are shared, theme-independent raster assets; only
 * the vector folder + emblem differ. Every SVG id is uniquified per instance via
 * useId() so multiple rows on screen never cross-reference one another's
 * gradients / clip paths / patterns.
 */
const IMG_BACK = `${__APP_ENV__.BASE_URL}/assets/knowledge/space-card-back.png`;
const IMG_FRONT = `${__APP_ENV__.BASE_URL}/assets/knowledge/space-card-front.png`;

const BLUE_INNER = `<g clip-path="url(#clip0___UID__)">
<rect width="48" height="48" rx="6" fill="white"/>
<rect width="48" height="48" rx="6" fill="url(#paint0_radial___UID__)" fill-opacity="0.4"/>
<rect width="48" height="48" rx="6" fill="white" fill-opacity="0.5"/>
<path d="M12.3999 11.4C12.3999 10.0745 13.4744 9 14.7999 9H41.9999C43.3254 9 44.3999 10.0745 44.3999 11.4V38.6C44.3999 39.9255 43.3254 41 41.9999 41H14.7999C13.4744 41 12.3999 39.9255 12.3999 38.6V11.4Z" fill="white"/>
<g clip-path="url(#clip1___UID__)">
<rect x="14.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
<rect x="6.7998" y="11.399" width="43.2" height="23.9855" fill="url(#pattern0___UID__)"/>
</g>
<rect x="14.9998" y="11.6" width="26.8" height="26.8" rx="1.4" stroke="#EBEBEB" stroke-width="0.4"/>
<g filter="url(#filter0_d___UID__)">
<rect x="8.3999" y="9" width="32" height="32" rx="2.4" fill="white" shape-rendering="crispEdges"/>
<g clip-path="url(#clip2___UID__)">
<rect x="10.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
<rect x="-0.000488281" y="11.399" width="48.8" height="27.2201" fill="url(#pattern1___UID__)"/>
</g>
<rect x="10.9998" y="11.6" width="26.8" height="26.8" rx="1.4" stroke="#EBEBEB" stroke-width="0.4"/>
</g>
<g filter="url(#filter1_d___UID__)">
<path d="M4.3999 11.4C4.3999 10.0745 5.47442 9 6.7999 9H33.9999C35.3254 9 36.3999 10.0745 36.3999 11.4V38.6C36.3999 39.9255 35.3254 41 33.9999 41H6.7999C5.47442 41 4.3999 39.9255 4.3999 38.6V11.4Z" fill="white" shape-rendering="crispEdges"/>
<rect x="6.7998" y="11.4" width="27.2" height="27.2" rx="3.4" fill="white"/>
<g opacity="0.3">
<path opacity="0.3" d="M23.7709 18.9871C23.3062 18.9867 22.8606 18.8019 22.532 18.4733C22.2034 18.1447 22.0186 17.6991 22.0182 17.2344V14.8009H14.1871C13.8867 14.8008 13.5891 14.8598 13.3115 14.9747C13.0339 15.0896 12.7817 15.2581 12.5692 15.4705C12.3567 15.6829 12.1881 15.9351 12.0731 16.2127C11.9581 16.4903 11.8989 16.7878 11.8989 17.0882V30.8769C11.8989 31.1774 11.9581 31.4749 12.0731 31.7525C12.1881 32.03 12.3567 32.2822 12.5692 32.4946C12.7817 32.707 13.0339 32.8755 13.3115 32.9904C13.5891 33.1053 13.8867 33.1644 14.1871 33.1643H23.5881C24.1948 33.1643 24.7766 32.9233 25.2055 32.4943C25.6345 32.0654 25.8755 31.4836 25.8755 30.8769V18.9871H23.7709Z" fill="#0072FF"/>
</g>
<path d="M25.8759 18.9871H23.7713C23.3066 18.9867 22.861 18.8019 22.5324 18.4733C22.2038 18.1447 22.019 17.6991 22.0186 17.2344V14.8009L25.8759 18.9871Z" fill="#0072FF"/>
<path d="M23.0005 21.918H14.2251C14.1408 21.918 14.06 21.8845 14.0003 21.8249C13.9407 21.7653 13.9072 21.6844 13.9072 21.6001C13.9071 21.5583 13.9153 21.5168 13.9312 21.4782C13.9471 21.4395 13.9705 21.4044 14 21.3747C14.0296 21.3451 14.0646 21.3217 14.1033 21.3056C14.1419 21.2896 14.1833 21.2813 14.2251 21.2813H23.0005C23.0851 21.2813 23.1661 21.3149 23.2259 21.3747C23.2857 21.4345 23.3193 21.5156 23.3193 21.6001C23.3191 21.6845 23.2854 21.7653 23.2256 21.8249C23.1659 21.8845 23.0849 21.918 23.0005 21.918V21.918Z" fill="#0072FF"/>
<path d="M23.0005 23.8194H14.2251C14.1408 23.8194 14.06 23.7859 14.0003 23.7262C13.9407 23.6666 13.9072 23.5858 13.9072 23.5015C13.9071 23.4596 13.9153 23.4182 13.9312 23.3795C13.9471 23.3409 13.9705 23.3057 14 23.2761C14.0296 23.2465 14.0646 23.223 14.1033 23.207C14.1419 23.191 14.1833 23.1827 14.2251 23.1827H23.0005C23.0851 23.1827 23.1661 23.2163 23.2259 23.2761C23.2857 23.3358 23.3193 23.4169 23.3193 23.5015C23.3191 23.5858 23.2854 23.6667 23.2256 23.7263C23.1659 23.7859 23.0849 23.8194 23.0005 23.8194V23.8194Z" fill="#0072FF"/>
<path d="M23.0005 25.7207H14.2251C14.1833 25.7207 14.1419 25.7125 14.1033 25.6964C14.0646 25.6804 14.0296 25.6569 14 25.6273C13.9705 25.5977 13.9471 25.5626 13.9312 25.5239C13.9153 25.4852 13.9071 25.4438 13.9072 25.402C13.9072 25.3177 13.9407 25.2368 14.0003 25.1772C14.06 25.1176 14.1408 25.0841 14.2251 25.0841H23.0005C23.0849 25.0841 23.1659 25.1175 23.2256 25.1771C23.2854 25.2367 23.3191 25.3176 23.3193 25.402C23.3193 25.4865 23.2857 25.5676 23.2259 25.6274C23.1661 25.6871 23.0851 25.7207 23.0005 25.7207Z" fill="#0072FF"/>
<path d="M19.5376 27.6221H14.2251C14.1833 27.6221 14.1419 27.6138 14.1033 27.5978C14.0646 27.5818 14.0296 27.5583 14 27.5287C13.9705 27.4991 13.9471 27.4639 13.9312 27.4253C13.9153 27.3866 13.9071 27.3452 13.9072 27.3033C13.9072 27.219 13.9407 27.1382 14.0003 27.0785C14.06 27.0189 14.1408 26.9854 14.2251 26.9854H19.5376C19.6219 26.9854 19.7028 27.0189 19.7624 27.0785C19.822 27.1382 19.8555 27.219 19.8555 27.3033C19.8556 27.3452 19.8475 27.3866 19.8316 27.4253C19.8156 27.4639 19.7922 27.4991 19.7627 27.5287C19.7332 27.5583 19.6981 27.5818 19.6595 27.5978C19.6209 27.6138 19.5794 27.6221 19.5376 27.6221Z" fill="#0072FF"/>
<path d="M27.535 29.3028H16.9066C16.1527 29.3028 15.5415 29.914 15.5415 30.6679V33.8367C15.5415 34.5906 16.1527 35.2018 16.9066 35.2018H27.535C28.2889 35.2018 28.9001 34.5906 28.9001 33.8367V30.6679C28.9001 29.914 28.2889 29.3028 27.535 29.3028Z" fill="#0072FF"/>
<path d="M17.9259 33.8767C17.838 33.8767 17.7626 33.8458 17.6998 33.784C17.6371 33.7221 17.6061 33.6468 17.6071 33.5579C17.6061 33.471 17.6371 33.3966 17.6998 33.3348C17.7626 33.273 17.838 33.2421 17.9259 33.2421C18.0109 33.2421 18.0848 33.273 18.1475 33.3348C18.2113 33.3966 18.2437 33.471 18.2446 33.5579C18.2437 33.6169 18.2282 33.6705 18.1983 33.7188C18.1693 33.7671 18.1306 33.8057 18.0823 33.8347C18.035 33.8627 17.9829 33.8767 17.9259 33.8767ZM19.8148 33.8448H18.8093V30.8775H19.8351C20.1297 30.8775 20.3828 30.9369 20.5943 31.0558C20.8068 31.1736 20.97 31.3431 21.084 31.5643C21.198 31.7855 21.255 32.0502 21.255 32.3583C21.255 32.6674 21.1975 32.933 21.0826 33.1552C20.9686 33.3773 20.8039 33.5478 20.5885 33.6666C20.3741 33.7854 20.1162 33.8448 19.8148 33.8448ZM19.3468 33.3797H19.7887C19.9954 33.3797 20.1679 33.3421 20.306 33.2667C20.4441 33.1904 20.5479 33.0769 20.6175 32.9262C20.687 32.7746 20.7218 32.5853 20.7218 32.3583C20.7218 32.1313 20.687 31.9429 20.6175 31.7932C20.5479 31.6425 20.4451 31.53 20.3089 31.4556C20.1737 31.3803 20.0056 31.3426 19.8047 31.3426H19.3468V33.3797ZM24.4171 32.3612C24.4171 32.6809 24.3573 32.9547 24.2375 33.1827C24.1187 33.4097 23.9564 33.5835 23.7507 33.7043C23.5459 33.825 23.3136 33.8854 23.0538 33.8854C22.7939 33.8854 22.5611 33.825 22.3554 33.7043C22.1506 33.5826 21.9884 33.4082 21.8686 33.1812C21.7498 32.9533 21.6904 32.6799 21.6904 32.3612C21.6904 32.0415 21.7498 31.7681 21.8686 31.5411C21.9884 31.3132 22.1506 31.1388 22.3554 31.0181C22.5611 30.8973 22.7939 30.837 23.0538 30.837C23.3136 30.837 23.5459 30.8973 23.7507 31.0181C23.9564 31.1388 24.1187 31.3132 24.2375 31.5411C24.3573 31.7681 24.4171 32.0415 24.4171 32.3612ZM23.8767 32.3612C23.8767 32.1361 23.8415 31.9463 23.7709 31.7918C23.7014 31.6363 23.6048 31.5189 23.4812 31.4397C23.3575 31.3595 23.2151 31.3194 23.0538 31.3194C22.8925 31.3194 22.75 31.3595 22.6263 31.4397C22.5027 31.5189 22.4056 31.6363 22.3351 31.7918C22.2656 31.9463 22.2308 32.1361 22.2308 32.3612C22.2308 32.5862 22.2656 32.7765 22.3351 32.932C22.4056 33.0866 22.5027 33.2039 22.6263 33.2841C22.75 33.3633 22.8925 33.4029 23.0538 33.4029C23.2151 33.4029 23.3575 33.3633 23.4812 33.2841C23.6048 33.2039 23.7014 33.0866 23.7709 32.932C23.8415 32.7765 23.8767 32.5862 23.8767 32.3612ZM27.4652 31.8787H26.9233C26.9079 31.7898 26.8794 31.7111 26.8378 31.6425C26.7963 31.573 26.7446 31.5141 26.6828 31.4658C26.621 31.4175 26.5505 31.3813 26.4713 31.3571C26.393 31.332 26.3085 31.3194 26.2177 31.3194C26.0564 31.3194 25.9135 31.36 25.7888 31.4412C25.6642 31.5213 25.5667 31.6392 25.4962 31.7947C25.4257 31.9492 25.3904 32.1381 25.3904 32.3612C25.3904 32.5882 25.4257 32.7794 25.4962 32.9349C25.5677 33.0895 25.6652 33.2064 25.7888 33.2856C25.9135 33.3638 26.0559 33.4029 26.2163 33.4029C26.3051 33.4029 26.3882 33.3913 26.4655 33.3681C26.5437 33.344 26.6137 33.3087 26.6756 33.2624C26.7383 33.216 26.791 33.159 26.8335 33.0914C26.8769 33.0238 26.9069 32.9465 26.9233 32.8596L27.4652 32.8625C27.4449 33.0035 27.401 33.1358 27.3333 33.2595C27.2667 33.3831 27.1793 33.4923 27.0711 33.5869C26.9629 33.6806 26.8364 33.754 26.6915 33.8071C26.5466 33.8593 26.3858 33.8854 26.209 33.8854C25.9482 33.8854 25.7154 33.825 25.5107 33.7043C25.3059 33.5835 25.1446 33.4092 25.0267 33.1812C24.9089 32.9533 24.85 32.6799 24.85 32.3612C24.85 32.0415 24.9094 31.7681 25.0282 31.5411C25.147 31.3132 25.3088 31.1388 25.5136 31.0181C25.7183 30.8973 25.9502 30.837 26.209 30.837C26.3742 30.837 26.5278 30.8602 26.6698 30.9065C26.8117 30.9529 26.9383 31.021 27.0494 31.1108C27.1604 31.1997 27.2517 31.3088 27.3232 31.4383C27.3956 31.5667 27.443 31.7135 27.4652 31.8787Z" fill="white"/>
</g>
<g opacity="0.9" filter="url(#filter2_d___UID__)">
<path d="M24.9517 26.2671C25.4472 26.9251 25.695 27.2541 25.9875 27.5157C26.5215 27.9933 27.174 28.3187 27.8769 28.4579C28.2617 28.5342 28.6736 28.5342 29.4974 28.5342H40C43.7712 28.5342 45.6569 28.5342 46.8284 29.7058C48 30.8773 48 32.7629 48 36.5342V59.3525C48 63.1238 48 65.0094 46.8284 66.181C45.6569 67.3525 43.7712 67.3525 40 67.3525H8C4.22876 67.3525 2.34315 67.3525 1.17157 66.181C0 65.0094 0 63.1238 0 59.3525V32C0 28.2288 0 26.3431 1.17157 25.1716C2.34315 24 4.22876 24 8 24H20.406C21.2297 24 21.6416 24 22.0265 24.0762C22.7293 24.2155 23.3818 24.5409 23.9158 25.0185C24.2083 25.2801 24.4561 25.6091 24.9517 26.2671Z" fill="white"/>
<path d="M24.9517 26.2671C25.4472 26.9251 25.695 27.2541 25.9875 27.5157C26.5215 27.9933 27.174 28.3187 27.8769 28.4579C28.2617 28.5342 28.6736 28.5342 29.4974 28.5342H40C43.7712 28.5342 45.6569 28.5342 46.8284 29.7058C48 30.8773 48 32.7629 48 36.5342V59.3525C48 63.1238 48 65.0094 46.8284 66.181C45.6569 67.3525 43.7712 67.3525 40 67.3525H8C4.22876 67.3525 2.34315 67.3525 1.17157 66.181C0 65.0094 0 63.1238 0 59.3525V32C0 28.2288 0 26.3431 1.17157 25.1716C2.34315 24 4.22876 24 8 24H20.406C21.2297 24 21.6416 24 22.0265 24.0762C22.7293 24.2155 23.3818 24.5409 23.9158 25.0185C24.2083 25.2801 24.4561 25.6091 24.9517 26.2671Z" fill="url(#paint1_radial___UID__)"/>
<path d="M24.9517 26.2671C25.4472 26.9251 25.695 27.2541 25.9875 27.5157C26.5215 27.9933 27.174 28.3187 27.8769 28.4579C28.2617 28.5342 28.6736 28.5342 29.4974 28.5342H40C43.7712 28.5342 45.6569 28.5342 46.8284 29.7058C48 30.8773 48 32.7629 48 36.5342V59.3525C48 63.1238 48 65.0094 46.8284 66.181C45.6569 67.3525 43.7712 67.3525 40 67.3525H8C4.22876 67.3525 2.34315 67.3525 1.17157 66.181C0 65.0094 0 63.1238 0 59.3525V32C0 28.2288 0 26.3431 1.17157 25.1716C2.34315 24 4.22876 24 8 24H20.406C21.2297 24 21.6416 24 22.0265 24.0762C22.7293 24.2155 23.3818 24.5409 23.9158 25.0185C24.2083 25.2801 24.4561 25.6091 24.9517 26.2671Z" fill="white" fill-opacity="0.4"/>
</g>
</g>
<defs>
<pattern id="pattern0___UID__" patternContentUnits="objectBoundingBox" width="1" height="1">
<use xlink:href="#image0___UID__" transform="scale(0.000502008 0.000904159)"/>
</pattern>
<filter id="filter0_d___UID__" x="8.3999" y="7.4" width="35.2" height="35.2" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
<feOffset dx="1.6"/>
<feGaussianBlur stdDeviation="0.8"/>
<feComposite in2="hardAlpha" operator="out"/>
<feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0.0406838 0 0 0 0 0.610258 0 0 0 0.05 0"/>
<feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow___UID__"/>
<feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow___UID__" result="shape"/>
</filter>
<pattern id="pattern1___UID__" patternContentUnits="objectBoundingBox" width="1" height="1">
<use xlink:href="#image1___UID__" transform="scale(0.000502513 0.000900901)"/>
</pattern>
<filter id="filter1_d___UID__" x="4.3999" y="7.4" width="35.2" height="35.2" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
<feOffset dx="1.6"/>
<feGaussianBlur stdDeviation="0.8"/>
<feComposite in2="hardAlpha" operator="out"/>
<feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0.0406838 0 0 0 0 0.610258 0 0 0 0.05 0"/>
<feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow___UID__"/>
<feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow___UID__" result="shape"/>
</filter>
<filter id="filter2_d___UID__" x="-8" y="12" width="64" height="59.3525" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
<feOffset dy="-4"/>
<feGaussianBlur stdDeviation="4"/>
<feComposite in2="hardAlpha" operator="out"/>
<feColorMatrix type="matrix" values="0 0 0 0 0.0673389 0 0 0 0 0.00625845 0 0 0 0 0.413462 0 0 0 0.05 0"/>
<feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow___UID__"/>
<feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow___UID__" result="shape"/>
</filter>
<radialGradient id="paint0_radial___UID__" cx="0" cy="0" r="1" gradientTransform="matrix(-46.4516 -49.7102 49.6552 -53.1385 48 48.0533)" gradientUnits="userSpaceOnUse">
<stop stop-color="#0068E7"/>
<stop offset="1" stop-color="#158DEF"/>
</radialGradient>
<radialGradient id="paint1_radial___UID__" cx="0" cy="0" r="1" gradientTransform="matrix(-46.4516 -44.8972 49.6552 -47.9936 48 67.4006)" gradientUnits="userSpaceOnUse">
<stop stop-color="#0068E7"/>
<stop offset="1" stop-color="#158DEF"/>
</radialGradient>
<clipPath id="clip0___UID__">
<rect width="48" height="48" rx="6" fill="white"/>
</clipPath>
<clipPath id="clip1___UID__">
<rect x="14.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
</clipPath>
<clipPath id="clip2___UID__">
<rect x="10.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
</clipPath>
<image id="image0___UID__" width="1992" height="1106" preserveAspectRatio="none" xlink:href="__IMG0__"/>
<image id="image1___UID__" width="1990" height="1110" preserveAspectRatio="none" xlink:href="__IMG1__"/>
</defs>`;

const GREEN_INNER = `<g clip-path="url(#clip0___UID__)">
<rect width="48" height="48" rx="6" fill="white"/>
<rect width="48" height="48" rx="6" fill="url(#paint0_radial___UID__)" fill-opacity="0.4"/>
<rect width="48" height="48" rx="6" fill="white" fill-opacity="0.5"/>
<path d="M12.3999 11.4C12.3999 10.0745 13.4744 9 14.7999 9H41.9999C43.3254 9 44.3999 10.0745 44.3999 11.4V38.6C44.3999 39.9255 43.3254 41 41.9999 41H14.7999C13.4744 41 12.3999 39.9255 12.3999 38.6V11.4Z" fill="white"/>
<g clip-path="url(#clip1___UID__)">
<rect x="14.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
<rect x="6.7998" y="11.399" width="43.2" height="23.9855" fill="url(#pattern0___UID__)"/>
</g>
<rect x="14.9998" y="11.6" width="26.8" height="26.8" rx="1.4" stroke="#EBEBEB" stroke-width="0.4"/>
<g filter="url(#filter0_d___UID__)">
<rect x="8.3999" y="9" width="32" height="32" rx="2.4" fill="white" shape-rendering="crispEdges"/>
<g clip-path="url(#clip2___UID__)">
<rect x="10.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
<rect x="-0.000488281" y="11.399" width="48.8" height="27.2201" fill="url(#pattern1___UID__)"/>
</g>
<rect x="10.9998" y="11.6" width="26.8" height="26.8" rx="1.4" stroke="#EBEBEB" stroke-width="0.4"/>
</g>
<g filter="url(#filter1_d___UID__)">
<path d="M4.3999 11.4C4.3999 10.0745 5.47442 9 6.7999 9H33.9999C35.3254 9 36.3999 10.0745 36.3999 11.4V38.6C36.3999 39.9255 35.3254 41 33.9999 41H6.7999C5.47442 41 4.3999 39.9255 4.3999 38.6V11.4Z" fill="white" shape-rendering="crispEdges"/>
<g opacity="0.3">
<path opacity="0.3" d="M24.1698 19.3862C23.7051 19.3858 23.2596 19.201 22.931 18.8724C22.6024 18.5438 22.4176 18.0982 22.4171 17.6335V15.2H14.5852C13.9786 15.2 13.3968 15.441 12.9678 15.8699C12.5388 16.2989 12.2979 16.8807 12.2979 17.4873V31.276C12.2979 31.8827 12.5388 32.4645 12.9678 32.8934C13.3968 33.3224 13.9786 33.5634 14.5852 33.5634H23.9862C24.5928 33.5634 25.1746 33.3224 25.6036 32.8934C26.0326 32.4645 26.2736 31.8827 26.2736 31.276V19.3862H24.1698Z" fill="#00C650"/>
</g>
<path d="M26.2744 19.3862H24.1707C23.706 19.3858 23.2604 19.201 22.9318 18.8724C22.6032 18.5438 22.4184 18.0982 22.418 17.6335V15.2L26.2744 19.3862Z" fill="#00C650"/>
<path d="M27.9315 29.735H17.3031C16.5492 29.735 15.938 30.3461 15.938 31.1001V34.2689C15.938 35.0228 16.5492 35.634 17.3031 35.634H27.9315C28.6854 35.634 29.2966 35.0228 29.2966 34.2689V31.1001C29.2966 30.3461 28.6854 29.735 27.9315 29.735Z" fill="#00C650"/>
<path d="M25.7471 32.277C25.7359 32.1716 25.6884 32.0895 25.6047 32.0307C25.5218 31.9719 25.4139 31.9426 25.2811 31.9426C25.1877 31.9426 25.1076 31.9567 25.0408 31.9848C24.974 32.013 24.9229 32.0512 24.8875 32.0995C24.8521 32.1478 24.8339 32.203 24.8331 32.2649C24.8331 32.3165 24.8448 32.3611 24.8682 32.399C24.8923 32.4368 24.9249 32.469 24.966 32.4955C25.007 32.5213 25.0525 32.543 25.1024 32.5607C25.1523 32.5785 25.2026 32.5933 25.2533 32.6054L25.4851 32.6634C25.5785 32.6851 25.6682 32.7145 25.7544 32.7515C25.8413 32.7885 25.919 32.8352 25.9874 32.8916C26.0566 32.9479 26.1114 33.0159 26.1516 33.0956C26.1919 33.1753 26.212 33.2687 26.212 33.3757C26.212 33.5206 26.1749 33.6482 26.1009 33.7585C26.0268 33.8679 25.9198 33.9537 25.7797 34.0156C25.6405 34.0768 25.4718 34.1074 25.2738 34.1074C25.0815 34.1074 24.9144 34.0776 24.7728 34.0181C24.6319 33.9585 24.5216 33.8716 24.4419 33.7573C24.3631 33.643 24.3204 33.5037 24.314 33.3395H24.7547C24.7611 33.4256 24.7877 33.4973 24.8343 33.5544C24.881 33.6116 24.9418 33.6542 25.0167 33.6824C25.0923 33.7106 25.1768 33.7247 25.2702 33.7247C25.3676 33.7247 25.4529 33.7102 25.5262 33.6812C25.6002 33.6514 25.6582 33.6104 25.7 33.558C25.7419 33.5049 25.7632 33.4429 25.764 33.3721C25.7632 33.3077 25.7443 33.2546 25.7073 33.2127C25.6703 33.1701 25.6183 33.1347 25.5515 33.1065C25.4855 33.0775 25.4083 33.0518 25.3197 33.0292L25.0384 32.9568C24.8348 32.9044 24.6738 32.8252 24.5554 32.7189C24.4379 32.6119 24.3792 32.4698 24.3792 32.2927C24.3792 32.147 24.4186 32.0194 24.4975 31.91C24.5772 31.8005 24.6854 31.7156 24.8223 31.6552C24.9591 31.594 25.1141 31.5634 25.2871 31.5634C25.4626 31.5634 25.6163 31.594 25.7483 31.6552C25.8812 31.7156 25.9854 31.7997 26.0611 31.9076C26.1367 32.0146 26.1758 32.1378 26.1782 32.277H25.7471Z" fill="white"/>
<path d="M22.4775 34.07V31.5973H22.9255V33.6945H24.0145V34.07H22.4775Z" fill="white"/>
<path d="M20.5042 31.5973L21.0488 32.5028H21.0681L21.615 31.5973H22.1258L21.3639 32.8336L22.1378 34.07H21.6187L21.0681 33.1705H21.0488L20.4982 34.07H19.9814L20.7626 32.8336L19.9911 31.5973H20.5042Z" fill="white"/>
<path d="M19.3941 34.0966C19.3208 34.0966 19.258 34.0708 19.2057 34.0193C19.1534 33.9678 19.1276 33.905 19.1284 33.8309C19.1276 33.7585 19.1534 33.6965 19.2057 33.645C19.258 33.5935 19.3208 33.5677 19.3941 33.5677C19.4649 33.5677 19.5265 33.5935 19.5788 33.645C19.6319 33.6965 19.6589 33.7585 19.6597 33.8309C19.6589 33.88 19.646 33.9247 19.621 33.9649C19.5969 34.0052 19.5647 34.0374 19.5245 34.0615C19.485 34.0849 19.4416 34.0966 19.3941 34.0966Z" fill="white"/>
<path d="M22.4043 28.0214H16.1721C15.6323 28.0214 15.1929 27.4842 15.1929 26.8229V22.3017C15.1929 21.6413 15.6323 21.1041 16.1721 21.1041H22.4068C22.9457 21.1041 23.3852 21.6413 23.3852 22.3017V26.8229C23.3826 27.4842 22.9432 28.0214 22.4043 28.0214ZM16.1721 21.7161C15.9077 21.7161 15.6935 21.9787 15.6935 22.3017V26.8229C15.6935 27.1459 15.9077 27.4085 16.1721 27.4085H22.4068C22.6703 27.4085 22.8845 27.1459 22.8845 26.8229V22.3017C22.8845 21.9787 22.6703 21.7161 22.4068 21.7161H16.1721Z" fill="#00C650"/>
<path d="M23.1326 25.2988H15.4409V25.9116H23.1326V25.2988Z" fill="#00C650"/>
<path d="M23.1326 23.1976H15.4409V23.8105H23.1326V23.1976Z" fill="#00C650"/>
<path d="M21.1622 21.4101H20.5493V27.7145H21.1622V21.4101Z" fill="#00C650"/>
<path d="M18.0235 21.4101H17.4106V27.7145H18.0235V21.4101Z" fill="#00C650"/>
</g>
<g opacity="0.9" filter="url(#filter2_d___UID__)">
<path d="M24.9517 26.2671C25.4472 26.9251 25.695 27.2541 25.9875 27.5157C26.5215 27.9933 27.174 28.3187 27.8769 28.4579C28.2617 28.5342 28.6736 28.5342 29.4974 28.5342H40C43.7712 28.5342 45.6569 28.5342 46.8284 29.7058C48 30.8773 48 32.7629 48 36.5342V59.3525C48 63.1238 48 65.0094 46.8284 66.181C45.6569 67.3525 43.7712 67.3525 40 67.3525H8C4.22876 67.3525 2.34315 67.3525 1.17157 66.181C0 65.0094 0 63.1238 0 59.3525V32C0 28.2288 0 26.3431 1.17157 25.1716C2.34315 24 4.22876 24 8 24H20.406C21.2297 24 21.6416 24 22.0265 24.0762C22.7293 24.2155 23.3818 24.5409 23.9158 25.0185C24.2083 25.2801 24.4561 25.6091 24.9517 26.2671Z" fill="white"/>
<path d="M24.9517 26.2671C25.4472 26.9251 25.695 27.2541 25.9875 27.5157C26.5215 27.9933 27.174 28.3187 27.8769 28.4579C28.2617 28.5342 28.6736 28.5342 29.4974 28.5342H40C43.7712 28.5342 45.6569 28.5342 46.8284 29.7058C48 30.8773 48 32.7629 48 36.5342V59.3525C48 63.1238 48 65.0094 46.8284 66.181C45.6569 67.3525 43.7712 67.3525 40 67.3525H8C4.22876 67.3525 2.34315 67.3525 1.17157 66.181C0 65.0094 0 63.1238 0 59.3525V32C0 28.2288 0 26.3431 1.17157 25.1716C2.34315 24 4.22876 24 8 24H20.406C21.2297 24 21.6416 24 22.0265 24.0762C22.7293 24.2155 23.3818 24.5409 23.9158 25.0185C24.2083 25.2801 24.4561 25.6091 24.9517 26.2671Z" fill="url(#paint1_radial___UID__)"/>
<path d="M24.9517 26.2671C25.4472 26.9251 25.695 27.2541 25.9875 27.5157C26.5215 27.9933 27.174 28.3187 27.8769 28.4579C28.2617 28.5342 28.6736 28.5342 29.4974 28.5342H40C43.7712 28.5342 45.6569 28.5342 46.8284 29.7058C48 30.8773 48 32.7629 48 36.5342V59.3525C48 63.1238 48 65.0094 46.8284 66.181C45.6569 67.3525 43.7712 67.3525 40 67.3525H8C4.22876 67.3525 2.34315 67.3525 1.17157 66.181C0 65.0094 0 63.1238 0 59.3525V32C0 28.2288 0 26.3431 1.17157 25.1716C2.34315 24 4.22876 24 8 24H20.406C21.2297 24 21.6416 24 22.0265 24.0762C22.7293 24.2155 23.3818 24.5409 23.9158 25.0185C24.2083 25.2801 24.4561 25.6091 24.9517 26.2671Z" fill="white" fill-opacity="0.4"/>
</g>
</g>
<defs>
<pattern id="pattern0___UID__" patternContentUnits="objectBoundingBox" width="1" height="1">
<use xlink:href="#image0___UID__" transform="scale(0.000502008 0.000904159)"/>
</pattern>
<filter id="filter0_d___UID__" x="8.3999" y="7.4" width="35.2" height="35.2" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
<feOffset dx="1.6"/>
<feGaussianBlur stdDeviation="0.8"/>
<feComposite in2="hardAlpha" operator="out"/>
<feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0.0406838 0 0 0 0 0.610258 0 0 0 0.05 0"/>
<feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow___UID__"/>
<feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow___UID__" result="shape"/>
</filter>
<pattern id="pattern1___UID__" patternContentUnits="objectBoundingBox" width="1" height="1">
<use xlink:href="#image1___UID__" transform="scale(0.000502513 0.000900901)"/>
</pattern>
<filter id="filter1_d___UID__" x="4.3999" y="7.4" width="35.2" height="35.2" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
<feOffset dx="1.6"/>
<feGaussianBlur stdDeviation="0.8"/>
<feComposite in2="hardAlpha" operator="out"/>
<feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0.0406838 0 0 0 0 0.610258 0 0 0 0.05 0"/>
<feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow___UID__"/>
<feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow___UID__" result="shape"/>
</filter>
<filter id="filter2_d___UID__" x="-8" y="12" width="64" height="59.3525" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
<feOffset dy="-4"/>
<feGaussianBlur stdDeviation="4"/>
<feComposite in2="hardAlpha" operator="out"/>
<feColorMatrix type="matrix" values="0 0 0 0 0.0673389 0 0 0 0 0.00625845 0 0 0 0 0.413462 0 0 0 0.05 0"/>
<feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow___UID__"/>
<feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow___UID__" result="shape"/>
</filter>
<radialGradient id="paint0_radial___UID__" cx="0" cy="0" r="1" gradientTransform="matrix(-46.4516 -49.7102 49.6552 -53.1385 48 48.0533)" gradientUnits="userSpaceOnUse">
<stop stop-color="#19B476"/>
<stop offset="1" stop-color="#63F3B9"/>
</radialGradient>
<radialGradient id="paint1_radial___UID__" cx="0" cy="0" r="1" gradientTransform="matrix(-46.4516 -44.8972 49.6552 -47.9936 48 67.4006)" gradientUnits="userSpaceOnUse">
<stop stop-color="#19B476"/>
<stop offset="1" stop-color="#63F3B9"/>
</radialGradient>
<clipPath id="clip0___UID__">
<rect width="48" height="48" rx="6" fill="white"/>
</clipPath>
<clipPath id="clip1___UID__">
<rect x="14.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
</clipPath>
<clipPath id="clip2___UID__">
<rect x="10.7998" y="11.4" width="27.2" height="27.2" rx="1.6" fill="white"/>
</clipPath>
<image id="image0___UID__" width="1992" height="1106" preserveAspectRatio="none" xlink:href="__IMG0__"/>
<image id="image1___UID__" width="1990" height="1110" preserveAspectRatio="none" xlink:href="__IMG1__"/>
</defs>`;

const hydrate = (tpl: string, uid: string): string =>
    tpl
        .replace(/__UID__/g, uid)
        .replace(/__IMG0__/g, IMG_BACK)
        .replace(/__IMG1__/g, IMG_FRONT);

export const KnowledgeSpaceIcon = ({ className, ...props }: React.SVGProps<SVGSVGElement>) => {
    const brand = useRecoilValue(store.brandTheme);
    const rawId = useId();
    // useId() emits ":r0:" style tokens — strip the colons so they're valid in SVG ids / url() refs.
    const uid = useMemo(() => rawId.replace(/:/g, ""), [rawId]);
    const inner = useMemo(
        () => hydrate(brand === "green" ? GREEN_INNER : BLUE_INNER, uid),
        [brand, uid],
    );

    return (
        <svg
            width="48"
            height="48"
            viewBox="0 0 48 48"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            xmlnsXlink="http://www.w3.org/1999/xlink"
            className={className}
            {...props}
            // Designer SVG (developer-controlled, no user input) is injected as-is to
            // avoid hand-porting ~60 elements of paths / filters / patterns to JSX.
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: inner }}
        />
    );
};
