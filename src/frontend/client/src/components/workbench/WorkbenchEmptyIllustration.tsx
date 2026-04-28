/**
 * Shared illustration for workstation empty placeholder (channel empty.png).
 */
export function WorkbenchEmptyIllustration() {
  const src = `${__APP_ENV__.BASE_URL || ''}/assets/channel/empty.png`;
  return (
    <img
      src={src}
      alt=""
      className="h-[120px] w-[120px] object-contain"
      width={120}
      height={120}
    />
  );
}
