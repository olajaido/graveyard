import { NightScene } from '@/components/art/night-scene';
import { RepoForm } from './repo-form';

export const NAV = [
  { href: '#how', label: 'How it works' },
  { href: '#states', label: 'The six states' },
  { href: '#evidence', label: 'Our evidence' },
  { href: 'https://github.com/olajaido/graveyard', label: 'GitHub' },
];

/** The hero: the night scene under the header, the promise and the form. */
export function Hero() {
  return (
    <section
      aria-label="Introduction"
      className="relative flex min-h-[760px] flex-col overflow-hidden bg-night"
    >
      <NightScene className="absolute inset-x-0 bottom-0 h-[640px] w-full" />
      <div className="container-page relative flex flex-col gap-[26px] pb-[300px] pt-44 sm:pt-[136px]">
        <p className="eyebrow m-0 text-bone-muted">Dependency autopsy · npm &amp; PyPI</p>
        <h1 className="m-0 max-w-[680px] font-display text-[clamp(48px,6.4vw,88px)] font-semibold leading-none tracking-[-0.01em]">
          Every codebase has a graveyard. <span className="italic text-cursed">Find yours.</span>
        </h1>
        <p className="m-0 max-w-[540px] text-[19px] text-bone-soft">
          We read your lockfiles, dig through every transitive dependency, and name the dead, the
          dying and the cursed, with the evidence to prove it.
        </p>
        <RepoForm />
      </div>
    </section>
  );
}
