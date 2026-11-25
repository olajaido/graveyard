import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Button, LinkButton } from './button';
import { Chip } from './chip';
import { Pill } from './pill';
import { StatusRegion } from './status-region';

describe('Button', () => {
  it('is a real button that never submits a form by accident', () => {
    render(<Button>Copy</Button>);
    expect(screen.getByRole('button', { name: 'Copy' })).toHaveAttribute('type', 'button');
  });
  it('a link button stays a link', () => {
    render(<LinkButton href="/">Exhume another</LinkButton>);
    expect(screen.getByRole('link', { name: 'Exhume another' })).toHaveAttribute('href', '/');
  });
});

describe('Chip', () => {
  it('toggles with aria-pressed and shows its count', async () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <Chip pressed={false} onToggle={onToggle} state="dead" count={17}>
        Dead
      </Chip>,
    );
    const chip = screen.getByRole('button', { name: 'Dead, 17' });
    expect(chip).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(chip);
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(
      <Chip pressed onToggle={onToggle} state="dead" count={17}>
        Dead
      </Chip>,
    );
    expect(screen.getByRole('button', { name: 'Dead, 17' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });
  it('is operable by keyboard', async () => {
    const onToggle = vi.fn();
    render(
      <Chip pressed={false} onToggle={onToggle}>
        All
      </Chip>,
    );
    await userEvent.tab();
    await userEvent.keyboard('{Enter}');
    expect(onToggle).toHaveBeenCalled();
  });
});

describe('Pill', () => {
  it('says the state in words', () => {
    render(<Pill tone="cursed">dead · cursed</Pill>);
    expect(screen.getByText('dead · cursed')).toBeInTheDocument();
  });
});

describe('StatusRegion', () => {
  it('is a polite status region that shows the message', () => {
    const { rerender } = render(<StatusRegion message="" />);
    const region = screen.getByRole('status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toBeEmptyDOMElement();
    rerender(<StatusRegion message="Exhumation complete" />);
    expect(region).toHaveTextContent('Exhumation complete');
  });
});
