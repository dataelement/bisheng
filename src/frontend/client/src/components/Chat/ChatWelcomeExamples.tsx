import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@bisheng/ui';
import type { resources } from '~/locales/i18n';
import catalog from './chatWelcomeExamples.json';

type ChatWelcomeExample = (typeof catalog.examples)[number];
type ExampleTitleId = keyof typeof resources.en.translation.dshChat.welcomeExamples.titles;
type ExampleFeedback = 'unavailable' | 'researchUnavailable' | 'keepAttachments';

export type ApplyChatWelcomeExample = (example: ChatWelcomeExample) => ExampleFeedback | undefined;

interface ChatWelcomeExamplesProps {
  onSelect: ApplyChatWelcomeExample;
}

// Use the original Desktop glyphs at the same 17px optical size.
const iconPaths = {
  mail: 'M6 5h12q3 0 3 3v8q0 3-3 3H6q-3 0-3-3V8q0-3 3-3z M3.7 7l7 5.4q1.3 1 2.6 0l7-5.4',
  news: 'M7.5 3h9Q19 3 19 5.5v13Q19 21 16.5 21h-9Q5 21 5 18.5v-13Q5 3 7.5 3z M8.5 7.5h7m-7 4.5h7m-7 4.5h4.5',
  compare: 'M5 5h3q2 0 2 2v10q0 2-2 2H5q-2 0-2-2V7q0-2 2-2z M16 5h3q2 0 2 2v10q0 2-2 2h-3q-2 0-2-2V7q0-2 2-2z M5.5 9h2m9 0h2',
  plan: 'M7 6h10q3 0 3 3v8q0 3-3 3H7q-3 0-3-3V9q0-3 3-3z M8 3.5V8m8-4.5V8M4 10.5h16m-11.5 4.5H10m4 0h1.5',
  notes: 'M8.5 5H7q-2 0-2 2v12q0 2 2 2h10q2 0 2-2V7q0-2-2-2h-1.5' +
    ' M10 3h4q1.5 0 1.5 1.5v1Q15.5 7 14 7h-4q-1.5 0-1.5-1.5v-1Q8.5 3 10 3z M8.5 11.5h7m-7 4h5',
  research: 'M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0z M14.25 14.25 20 20',
};

const examplesById = new Map(catalog.examples.map((example) => [example.id, example]));
const batches = catalog.batches.map((ids) => ids.map((id) => examplesById.get(id)!));

export function ChatWelcomeExamples({ onSelect }: ChatWelcomeExamplesProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const [batchIndex, setBatchIndex] = useState(0);
  const [feedback, setFeedback] = useState<ExampleFeedback>();

  function handleNextBatch() {
    setFeedback(undefined);
    setBatchIndex((index) => (index + 1) % batches.length);
  }

  return (
    <section className="chat-welcome-examples" aria-labelledby={headingId}>
      <div className="chat-welcome-examples-header">
        <h3 id={headingId}>{t('dshChat.welcomeExamples.heading')}</h3>
        <Button color="default" variant="text" size="small" className="chat-welcome-examples-next" onClick={handleNextBatch}>
          {t('dshChat.welcomeExamples.next')}
        </Button>
      </div>
      <ul key={batchIndex} className="chat-welcome-examples-list">
        {batches[batchIndex].map((example) => {
          const path = iconPaths[example.icon as keyof typeof iconPaths];
          const titleId = example.id as ExampleTitleId;
          return (
            <li key={example.id}>
              <Button color="default" variant="text" size="large" className="chat-welcome-example" onClick={() => setFeedback(onSelect(example))}>
                <span className="chat-welcome-example-icon" data-icon={example.icon} aria-hidden="true">
                  <svg viewBox="0 0 24 24" focusable="false">
                    <path d={path} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span>{t(`dshChat.welcomeExamples.titles.${titleId}`)}</span>
              </Button>
            </li>
          );
        })}
      </ul>
      <p role="status" className="chat-welcome-examples-feedback">
        {feedback && t(`dshChat.welcomeExamples.${feedback}`)}
      </p>
    </section>
  );
}
