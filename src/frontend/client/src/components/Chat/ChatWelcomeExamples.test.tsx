import { fireEvent, render, screen, within } from '@testing-library/react';
import i18n from '~/locales/i18n';
import { ChatWelcomeExamples } from './ChatWelcomeExamples';

it('cycles the desktop batches in order and reports a failed draft selection', async () => {
  await i18n.changeLanguage('en');
  const onSelect = jest.fn().mockReturnValueOnce('researchUnavailable');
  render(<ChatWelcomeExamples onSelect={onSelect} />);

  const examples = within(screen.getByRole('region', { name: 'Start with an example' }));
  const nextBatch = examples.getByRole('button', { name: 'Try another set' });
  const titles = () => examples.getAllByRole('button')
    .filter((button) => button !== nextBatch)
    .map((button) => button.textContent);
  const firstBatch = [
    'Draft an event confirmation email',
    'Catch up on AI news',
    'Research enterprise AI agents',
    'Compare noise-canceling headphones',
  ];
  expect(titles()).toEqual(firstBatch);

  fireEvent.click(nextBatch);
  expect(titles()).toEqual([
    'Scope an appointment tracker',
    'Organize customer feedback',
    'Compare digital museum collections',
    'Research urban cooling measures',
  ]);
  const museumExample = examples.getByRole('button', { name: 'Compare digital museum collections' });
  fireEvent.click(museumExample);
  expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({
    id: 'museum-collections',
    deepResearch: true,
    prompt: expect.stringContaining('Markdown'),
  }));
  const failure = i18n.t('dshChat.welcomeExamples.researchUnavailable');
  expect(examples.getByRole('status')).toHaveTextContent(failure);

  fireEvent.click(museumExample);
  expect(examples.queryByText(failure)).not.toBeInTheDocument();

  fireEvent.click(nextBatch);
  expect(titles()).toEqual([
    'Compare team event options',
    'Research commercial space revenue',
    'Draft an event confirmation email',
    'Compare digital museum collections',
  ]);
  fireEvent.click(nextBatch);
  expect(titles()).toEqual(firstBatch);
  expect(onSelect).toHaveBeenCalledTimes(2);
});
