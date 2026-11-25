import type { ButtonHTMLAttributes, ComponentProps } from 'react';
import { AppLink } from '@/components/layout/app-link';

type Variant = 'primary' | 'secondary';
type Size = 'normal' | 'large';

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-md font-semibold no-underline cursor-pointer disabled:cursor-not-allowed disabled:opacity-70';
const VARIANT: Record<Variant, string> = {
  primary: 'bg-bone text-on-bone hover:bg-white border border-bone',
  secondary: 'bg-ground text-bone border border-control-line hover:border-bone-quiet',
};
const SIZE: Record<Size, string> = {
  normal: 'h-11 px-[18px] text-[15px]',
  large: 'h-[54px] px-[26px] text-base',
};

export function buttonClass(variant: Variant = 'primary', size: Size = 'normal'): string {
  return `${BASE} ${VARIANT[variant]} ${SIZE[size]}`;
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size };

/** A real `<button>`. Type defaults to `button`, so it never submits a form by accident. */
export function Button({ variant, size, className, type = 'button', ...rest }: ButtonProps) {
  return (
    <button type={type} className={`${buttonClass(variant, size)} ${className ?? ''}`} {...rest} />
  );
}

/** A link that looks like a button. It stays a link. */
export function LinkButton({
  variant,
  size,
  className,
  ...rest
}: ComponentProps<typeof AppLink> & { variant?: Variant; size?: Size }) {
  return <AppLink className={`${buttonClass(variant, size)} ${className ?? ''}`} {...rest} />;
}
