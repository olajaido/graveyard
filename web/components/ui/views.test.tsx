import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ERROR_COPY } from '@/lib/api/errors';
import { expectNoViolations } from '@/lib/test/axe';
import { CopyLinkButton } from './copy-link-button';
import { ErrorView } from './error-view';
import { NotFoundView } from './not-found-view';

describe('ErrorView', () => {
  it('moves focus to its heading, so it is announced', () => {
    render(<ErrorView copy={ERROR_COPY.NO_MANIFESTS} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Nothing buried here' })).toHaveFocus();
  });

  it('says what to do: edit goes back to the form', () => {
    render(<ErrorView copy={ERROR_COPY.REPO_NOT_FOUND} detail="olajaido/missing" />);
    expect(screen.getByText('olajaido/missing')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Try another repository' })).toHaveAttribute(
      'href',
      '/',
    );
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('offers a retry only for an error a retry can help, and wires it', async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <ErrorView copy={ERROR_COPY.GITHUB_RATE_LIMITED} onRetry={onRetry} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    rerender(<ErrorView copy={ERROR_COPY.TOO_LARGE} onRetry={onRetry} />);
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('links back when it has somewhere to go back to', () => {
    render(
      <ErrorView copy={ERROR_COPY.INTERNAL} backHref="/scan?id=x" backLabel="Back to the scan" />,
    );
    expect(screen.getByRole('link', { name: 'Back to the scan' })).toHaveAttribute(
      'href',
      '/scan?id=x',
    );
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <ErrorView copy={ERROR_COPY.GITHUB_RATE_LIMITED} onRetry={() => undefined} backHref="/" />
      </main>,
    );
    await expectNoViolations(container);
  });
});

describe('NotFoundView', () => {
  it.each([
    ['scan', 'This plot is not on the map'],
    ['grave', 'No such grave in this plot'],
    ['path', 'This page is not on the map'],
  ] as const)('%s', (kind, title) => {
    render(<NotFoundView kind={kind} />);
    expect(screen.getByRole('heading', { level: 1, name: title })).toHaveFocus();
    expect(screen.getByText(/30 days/)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /gate|repository/i }).length).toBeGreaterThan(0);
  });
  it('links back to the scan from a grave', () => {
    render(
      <NotFoundView
        kind="grave"
        backHref="/scan?id=x"
        backLabel="Back to olajaido/haunted-house"
      />,
    );
    expect(
      screen.getByRole('link', { name: 'Back to olajaido/haunted-house' }),
    ).toBeInTheDocument();
  });
  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <NotFoundView />
      </main>,
    );
    await expectNoViolations(container);
  });
});

describe('CopyLinkButton', () => {
  it('copies the address and says so in the status region', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<CopyLinkButton label="Copy link to this scan" />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy link to this scan' }));
    expect(writeText).toHaveBeenCalledWith(window.location.href);
    expect(screen.getByRole('status')).toHaveTextContent('Link copied.');
    expect(screen.getByRole('button', { name: 'Link copied' })).toBeInTheDocument();
  });

  it('shows the link in a field to copy by hand when the clipboard is refused', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });
    render(<CopyLinkButton label="Copy link" />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy link' }));
    const field = screen.getByRole('textbox', { name: 'Link to copy' });
    expect(field).toHaveValue(window.location.href);
    expect(field).toHaveAttribute('readonly');
    expect(screen.getByRole('status')).toHaveTextContent('Copy the link from the box.');
  });

  it('shows the field too when there is no clipboard at all', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    render(<CopyLinkButton label="Copy link" />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy link' }));
    expect(screen.getByRole('textbox', { name: 'Link to copy' })).toBeInTheDocument();
  });
});
