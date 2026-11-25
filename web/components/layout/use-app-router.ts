'use client';
import { useRouter } from 'next/navigation';

/** The one place components touch `next/navigation`, next to `AppLink`. */
export function useAppRouter(): { push: (href: string) => void } {
  const router = useRouter();
  return { push: (href) => router.push(href) };
}
