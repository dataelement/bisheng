import { render, screen } from '@testing-library/react';
import { createInstance } from 'i18next';
import en from '~/locales/en/translation.json';
import ja from '~/locales/ja/translation.json';
import zh from '~/locales/zh-Hans/translation.json';
import { ConversationHistoryDate } from './ConversationHistoryDate';

const mockI18n = createInstance();
jest.mock('~/hooks', () => ({ useLocalize: () => mockI18n.t.bind(mockI18n) }));

const now = Date.parse('2026-11-25T08:00:00Z');
const minute = 60 * 1000;
const hour = 60 * minute;
const day = 24 * hour;

beforeAll(async () => {
  await mockI18n.init({
    lng: 'en',
    resources: { en: { translation: en }, ja: { translation: ja }, 'zh-Hans': { translation: zh } },
  });
});

beforeEach(async () => {
  await mockI18n.changeLanguage('en');
  jest.spyOn(Date, 'now').mockReturnValue(now);
});

it.each([
  [-minute, 'now'],
  [minute - 1, 'now'],
  [minute, '1min'],
  [hour - 1, '59min'],
  [hour, '1h'],
  [day - 1, '23h'],
  [day, '1d'],
  [30 * day - 1, '29d'],
  [30 * day, '1mo'],
  [365 * day - 1, '12mo'],
  [365 * day, '1y'],
])('shows the desktop time label at %i elapsed milliseconds', (elapsed, label) => {
  const updatedAt = new Date(now - elapsed).toISOString();
  render(<ConversationHistoryDate updatedAt={updatedAt} className="history-age" />);
  const time = screen.getByText(label);
  expect(time).toHaveAttribute('dateTime', updatedAt);
  expect(time).toHaveClass('history-age');
});

it.each([
  ['zh-Hans', zh.com_workbench_sidebar.conversation_age],
  ['ja', ja.com_workbench_sidebar.conversation_age],
] as const)('uses the interface language %s for the compact label', async (language, messages) => {
  await mockI18n.changeLanguage(language);
  const { rerender } = render(<ConversationHistoryDate updatedAt={new Date(now).toISOString()} className="history-age" />);
  expect(screen.getByText(messages.now)).toBeInTheDocument();
  rerender(<ConversationHistoryDate updatedAt={new Date(now - 2 * day).toISOString()} className="history-age" />);
  expect(screen.getByText(messages.days.replace('{{n}}', '2'))).toBeInTheDocument();
});

it('prefers the update time and falls back to creation time when it is missing', () => {
  const createdAt = '2026-11-20T16:00:00+08:00';
  const updatedAt = '2026-11-23T16:00:00+08:00';
  const { rerender } = render(<ConversationHistoryDate createdAt={createdAt} updatedAt={updatedAt} className="history-age" />);
  expect(screen.getByText('2d')).toHaveAttribute('dateTime', '2026-11-23T08:00:00.000Z');
  rerender(<ConversationHistoryDate createdAt={createdAt} updatedAt="" className="history-age" />);
  expect(screen.getByText('5d')).toHaveAttribute('dateTime', '2026-11-20T08:00:00.000Z');
});

it.each([undefined, 'invalid-date'])('omits the label for a missing or invalid timestamp (%s)', (updatedAt) => {
  const { container } = render(<ConversationHistoryDate updatedAt={updatedAt} className="history-age" />);
  expect(container).toBeEmptyDOMElement();
});
