import { cn } from "~/utils";
import useFinePointer from "~/hooks/useFinePointer";
import useLocalize from "~/hooks/useLocalize";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { Popover, PopoverArrow, PopoverContent, PopoverTrigger } from "~/components/ui/Popover";
// Imported as a module (not a /public URL) so the bundler resolves it against
// the app's base path and fingerprints it — no env-var lookup at render time.
import wechatCopyLinkGuide from "./wechat-copy-link-guide.png";

/** Shared card body for the "where do I copy a WeChat article link from" guide. */
const WECHAT_GUIDE_CARD =
    "w-[280px] max-w-[calc(100vw-24px)] rounded-md border-none bg-white p-3 text-left text-xs leading-5 text-text-3 shadow-[0_4px_16px_rgba(0,0,0,0.12)]";

/**
 * A sentence with one highlighted phrase that opens the "where do I copy a
 * WeChat article link from" guide. Used both after a link fails to resolve and
 * when a search turns up nothing — each passes its own copy, since the two
 * moments word the advice differently.
 *
 * The sentence is one i18n key with a `{{link}}` placeholder so translators keep
 * control of word order; it is split back apart on the localized phrase.
 *
 * Two affordances, picked by input type rather than viewport: a hover Tooltip
 * where a fine pointer exists, a tap-to-open Popover everywhere else. A Radix
 * Tooltip is unreachable by touch — the tap that would open it also closes it —
 * so on a phone or a touch panel this guide was simply unavailable.
 */
export function WechatLinkHint({
    className,
    sentenceKey,
    labelKey,
}: {
    className?: string;
    sentenceKey: string;
    labelKey: string;
}) {
    const localize = useLocalize();
    const hasHover = useFinePointer();
    const linkLabel = localize(labelKey);
    const sentence = localize(sentenceKey, { link: linkLabel });
    const splitAt = sentence.indexOf(linkLabel);

    const guideBody = (
        <>
            <img src={wechatCopyLinkGuide} alt="" className="mx-auto mb-2 w-[160px] rounded" />
            {/* Size/colour live on the <p> itself, matching the sentence that
                owns the trigger — inheriting from the panel lets the panel's
                own text-* classes compete with them. */}
            <p className="text-[12px] leading-5 text-[#999999]">
                {localize("com_subscription.wechat_link_copy_tip")}
            </p>
        </>
    );

    // mx-1 gives the highlighted phrase breathing room from the grey text on
    // both sides; CJK copy has no natural word spacing.
    const highlighted = hasHover ? (
        <Tooltip>
            <TooltipTrigger asChild>
                <span className="mx-1 cursor-pointer text-blue-500 no-underline">{linkLabel}</span>
            </TooltipTrigger>
            <TooltipContent
                side="top"
                className={WECHAT_GUIDE_CARD}
                arrowClassName="bg-white fill-white"
            >
                {guideBody}
            </TooltipContent>
        </Tooltip>
    ) : (
        <Popover>
            <PopoverTrigger asChild>
                {/* Underlined + a real button: without a hover state, nothing
                    else tells a touch user the phrase is tappable. `py-1 -my-1`
                    grows the touch target without changing the line box. */}
                <button
                    type="button"
                    className="mx-1 -my-1 inline py-1 text-blue-500 underline underline-offset-[3px] active:opacity-70"
                >
                    {linkLabel}
                </button>
            </PopoverTrigger>
            <PopoverContent
                side="top"
                sideOffset={6}
                collisionPadding={12}
                className={WECHAT_GUIDE_CARD}
            >
                {guideBody}
                <PopoverArrow className="bg-white fill-white" />
            </PopoverContent>
        </Popover>
    );

    // Defensive: a translation that dropped the placeholder still renders readably.
    if (splitAt === -1) {
        return <p className={cn("text-[14px] font-normal text-[#999999]", className)}>{sentence}</p>;
    }

    return (
        <p className={cn("text-[14px] font-normal leading-[22px] text-[#999999]", className)}>
            {/* Trim the seam so `mx-1` is the only gap — languages that already
                separate words with spaces would otherwise read as a double space. */}
            {sentence.slice(0, splitAt).replace(/\s+$/, "")}
            {highlighted}
            {sentence.slice(splitAt + linkLabel.length).replace(/^\s+/, "")}
        </p>
    );
}
