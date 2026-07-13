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
      <div className="flex h-full flex-col items-center justify-center max-md:justify-start max-md:pt-2 max-md:pb-4 px-4">
        {/* Hero: row on ≥768 (matches the desktop shell), stacked only on the H5 shell (≤767) */}
        <div className="flex flex-col items-center gap-3 md:flex-row md:gap-4">
          {bsConfig?.assistantIcon?.image && (
            <img
              className="overflow-hidden w-[52px] h-[52px] object-contain shrink-0"
              src={__APP_ENV__.BASE_URL + bsConfig.assistantIcon.image}
              alt=""
            />
          )}
          <h2 className="max-w-full md:max-w-[75vw] text-center text-xl md:text-2xl font-semibold md:font-medium leading-snug md:leading-8 text-[#1d2129] dark:text-white px-0">
            {bsConfig?.welcomeMessage}
          </h2>
        </div>
        {!hideSubtitle && (
          <div className="max-w-lg text-center mt-[26px] text-sm font-normal text-gray-500 leading-5">
            {bsConfig?.functionDescription}
          </div>
        )}

        {/* Conversation starters */}
        {conversation_starters.length > 0 && (
          <div className="mt-5 md:mt-6 w-full max-w-2xl flex flex-wrap justify-center gap-2">
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
