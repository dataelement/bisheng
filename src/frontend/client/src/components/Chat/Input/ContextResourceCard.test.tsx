import { fireEvent, render, screen } from '@testing-library/react';
import { ContextResourceCard } from './ContextResourceCard';
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));

test('file and knowledge resources share names and metadata, removing never opens a preview', () => {
  const preview = jest.fn();
  const removeFile = jest.fn();
  const removeSpace = jest.fn();
  render(<>
    <ContextResourceCard label="Brief.pdf" description="PDF · 1.2 MB" icon={<span>PDF</span>} onClick={preview} onRemove={removeFile} />
    <ContextResourceCard label="Product research" description="Knowledge space" icon={<span>KB</span>} onRemove={removeSpace} />
  </>);
  expect(screen.getByText('Knowledge space')).toBeInTheDocument();
  expect(screen.getByText('PDF · 1.2 MB')).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole('button', { name: /Brief.pdf/ }), { key: 'Enter' });
  expect(preview).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove', exact: true })[1]);
  expect(removeSpace).toHaveBeenCalledTimes(1);
  expect(removeFile).not.toHaveBeenCalled();
  expect(preview).toHaveBeenCalledTimes(1);
});
