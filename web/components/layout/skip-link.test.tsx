import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { SkipLink } from './skip-link';

describe('SkipLink', () => {
  it('is the first tab stop and points at main', async () => {
    render(
      <>
        <SkipLink />
        <button type="button">Other</button>
        <main id="main" />
      </>,
    );
    await userEvent.tab();
    const link = screen.getByRole('link', { name: 'Skip to content' });
    expect(link).toHaveFocus();
    expect(link).toHaveAttribute('href', '#main');
  });
});
