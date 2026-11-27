import { fireEvent, render, screen } from '@/test/test-utils';
import { expect, it, vi } from 'vitest';
import SourceEntry from './SourceEntry';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

it('keeps the historical file source action and hides it for new registry-only replies', () => {
  const onSource = vi.fn();
  const { rerender } = render(<SourceEntry extra={{}} end source={1} onSource={onSource} />);
  fireEvent.click(screen.getByRole('button', { name: 'chat.source' }));
  expect(onSource).toHaveBeenCalledOnce();

  rerender(<SourceEntry extra={{}} end source={0} onSource={onSource} />);
  expect(screen.queryByRole('button', { name: 'chat.source' })).not.toBeInTheDocument();
});
