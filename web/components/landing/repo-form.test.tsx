import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
import { mockApi } from '@/mocks/node';
import { HAUNTED_SCAN_ID } from '@/mocks/fixtures/haunted-house';
import { expectNoViolations } from '@/lib/test/axe';
import { RepoForm } from './repo-form';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

async function type(value: string) {
  const input = screen.getByLabelText('Public GitHub repository');
  await userEvent.clear(input);
  if (value) await userEvent.type(input, value);
  return input;
}

describe('RepoForm', () => {
  it('has a label, the prefix and a submit button, pre-filled with the haunted house', () => {
    render(<RepoForm create={vi.fn()} />);
    expect(screen.getByLabelText('Public GitHub repository')).toHaveValue('olajaido/haunted-house');
    expect(screen.getByRole('button', { name: 'Exhume' })).toHaveAttribute('type', 'submit');
    expect(screen.getByText(/Nothing is\s+installed or run/)).toBeInTheDocument();
  });

  it('posts owner/name and moves to the scan page', async () => {
    push.mockClear();
    const create = vi.fn().mockResolvedValue({ scanId: HAUNTED_SCAN_ID, status: 'QUEUED' });
    render(<RepoForm create={create} />);
    await type('https://github.com/olajaido/haunted-house.git');
    await userEvent.click(screen.getByRole('button', { name: 'Exhume' }));
    expect(create).toHaveBeenCalledWith('olajaido/haunted-house');
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/scan?id=${HAUNTED_SCAN_ID}`));
  });

  it('submits with the Enter key', async () => {
    push.mockClear();
    const create = vi.fn().mockResolvedValue({ scanId: HAUNTED_SCAN_ID, status: 'QUEUED' });
    render(<RepoForm create={create} />);
    await userEvent.type(await type('a/b'), '{Enter}');
    expect(create).toHaveBeenCalledWith('a/b');
  });

  it.each(['', 'nonsense', 'a/b/c', 'https://gitlab.com/a/b', 'a/b?x=1'])(
    'refuses %j before any request, ties the message to the input and focuses it',
    async (text) => {
      const create = vi.fn();
      render(<RepoForm create={create} />);
      const input = await type(text);
      await userEvent.click(screen.getByRole('button', { name: 'Exhume' }));
      expect(create).not.toHaveBeenCalled();
      expect(await screen.findByText(/That is not a grave site/)).toBeInTheDocument();
      expect(input).toHaveAttribute('aria-invalid', 'true');
      expect(input.getAttribute('aria-describedby')).toContain('repo-error');
      await waitFor(() => expect(input).toHaveFocus());
    },
  );

  it('shows "Digging…" and disables the button while it waits', async () => {
    let finish: (v: { scanId: string; status: 'QUEUED' }) => void = () => undefined;
    const create = vi.fn(
      () => new Promise<{ scanId: string; status: 'QUEUED' }>((r) => (finish = r)),
    );
    render(<RepoForm create={create} />);
    await userEvent.click(screen.getByRole('button', { name: 'Exhume' }));
    const busy = screen.getByRole('button', { name: 'Digging…' });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute('aria-busy', 'true');
    await userEvent.click(busy);
    expect(create).toHaveBeenCalledTimes(1);
    finish({ scanId: HAUNTED_SCAN_ID, status: 'QUEUED' });
  });

  it.each([
    [new ApiError('problem', 429), 'Too many digs at once'],
    [new ApiError('problem', 503), 'The crypt is resting'],
    [new ApiError('problem', 500), 'Something went wrong underground'],
    [new ApiError('network'), 'The path is out of reach'],
    [new Error('boom'), 'The path is out of reach'],
  ])('stays on the page and says what went wrong for %j', async (error, title) => {
    push.mockClear();
    render(<RepoForm create={vi.fn().mockRejectedValue(error)} />);
    await userEvent.click(screen.getByRole('button', { name: 'Exhume' }));
    expect(await screen.findByText(new RegExp(title))).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Exhume' })).toBeEnabled();
    await waitFor(() => expect(screen.getByLabelText('Public GitHub repository')).toHaveFocus());
  });

  it('works against the mocked API, and a 503 of the API reads as the crypt resting', async () => {
    mockApi({ createError: { status: 503 } });
    render(<RepoForm />);
    await userEvent.click(screen.getByRole('button', { name: 'Exhume' }));
    expect(await screen.findByText(/The crypt is resting/)).toBeInTheDocument();
  });

  it('has no axe violations, with or without an error', async () => {
    const { container } = render(<RepoForm create={vi.fn()} />);
    await expectNoViolations(container);
    await userEvent.clear(screen.getByLabelText('Public GitHub repository'));
    await userEvent.click(screen.getByRole('button', { name: 'Exhume' }));
    await screen.findByText(/That is not a grave site/);
    await expectNoViolations(container);
  });
});
