import { useState, type ReactNode } from 'react';
import { useSearchParams } from "react-router-dom";
import { useLocalize } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { Constants } from '~/types/chat';
import ConvoStarter from './ConvoStarter';

export default function Landing({ Header, isNew, hideSubtitle = false }: {
  Header?: ReactNode;
  isNew?: boolean;
  /**
   * Hide the welcome subtitle while the input has a mounted knowledge space /
   * file. The subtitle's vertical footprint (≈46px) is exactly compensated by
   * the attachment bar growing the input box upward, so the title and input box
   * stay put (Figma 12841:46839 vs 12841:47077).
   */
  hideSubtitle?: boolean;
}) {
  const { data: bsConfig } = useGetBsConfig();
  const localize = useLocalize();
  const [searchParams] = useSearchParams();
  const defaultCategory = searchParams.get('category') || 'favorites';

  const [activeCategory, setActiveCategory] = useState<string>(defaultCategory)

  // Conversation starters from bsConfig
  const conversation_starters = ((bsConfig as { conversationStarters?: string[] } | undefined)?.conversationStarters) ?? [];

  return (
    <div className={`relative ${!isNew ? 'h-full' : ''}`}>
      <div className="absolute left-0 right-0">{Header != null ? Header : null}</div>
      <div className="flex h-full flex-col items-center justify-center touch-mobile:justify-start touch-mobile:pt-2 touch-mobile:pb-4 px-4">
        {/* Hero: stack vertically on 576 稿 */}
        <div className="flex flex-col touch-mobile:flex-col items-center gap-3 touch-mobile:gap-3 touch-desktop:flex-row touch-desktop:gap-4">
          {bsConfig?.assistantIcon?.image && (
            <img
              className="overflow-hidden touch-mobile:w-14 touch-mobile:h-14 w-[52px] h-[52px] object-contain shrink-0"
              src={__APP_ENV__.BASE_URL + bsConfig.assistantIcon.image}
              alt=""
            />
          )}
          <h2 className="max-w-[75vh] touch-mobile:max-w-full text-center text-xl touch-mobile:font-semibold touch-mobile:text-[#1d2129] touch-mobile:leading-snug font-medium dark:text-white touch-desktop:text-2xl px-0">
            {bsConfig?.welcomeMessage}
          </h2>
        </div>
        {!hideSubtitle && (
          <div className="max-w-lg touch-mobile:max-w-full text-center mt-[26px] touch-mobile:mt-3 text-sm touch-mobile:text-[13px] font-normal text-gray-500 touch-mobile:text-[#4e5969] leading-5 touch-mobile:leading-relaxed">
            {bsConfig?.functionDescription}
          </div>
        )}

        {/* Conversation starters */}
        {conversation_starters.length > 0 && (
          <div className="mt-6 touch-mobile:mt-5 w-full max-w-2xl flex flex-wrap justify-center gap-2 touch-mobile:gap-2 touch-mobile:px-0">
            {conversation_starters
              .slice(0, Constants.MAX_CONVO_STARTERS)
              .map((text: string, index: number) => (
                <ConvoStarter
                  key={index}
                  text={text}
                  onClick={() => {
                    // Conversation starter click is handled in parent
                    console.log('Convo starter clicked:', text);
                  }}
                />
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
