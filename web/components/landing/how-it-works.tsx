import { StepArt, type Step } from '@/components/art/step-art';

const ACTS: { act: string; step: Step; title: string; text: string }[] = [
  {
    act: 'Act I',
    step: 'exhume',
    title: 'Exhume',
    text: 'A read-only GitHub App digs up only your lockfiles. No clone, no install, no code run.',
  },
  {
    act: 'Act II',
    step: 'identify',
    title: 'Identify',
    text: 'Every body gets a toe tag. Syft names each package and version exactly.',
  },
  {
    act: 'Act III',
    step: 'trace',
    title: 'Trace the roots',
    text: 'We follow every root underground: what you chose, and what came along with it.',
  },
  {
    act: 'Act IV',
    step: 'pronounce',
    title: 'Pronounce',
    text: "Dead is only ever sealed on evidence: a deprecation, an archive, the maintainer's own word.",
  },
];

export function HowItWorks() {
  return (
    <section
      id="how"
      aria-labelledby="how-title"
      className="cv-auto scroll-mt-4 border-t border-hairline bg-night-alt"
    >
      <div className="container-page flex flex-col gap-12 py-16 sm:py-[88px]">
        <h2
          id="how-title"
          className="m-0 font-display text-[clamp(36px,5vw,52px)] font-semibold leading-[1.1]"
        >
          The autopsy, in four acts
        </h2>
        <ol className="m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(min(100%,250px),1fr))] gap-5 p-0">
          {ACTS.map((a) => (
            <li
              key={a.title}
              className="flex flex-col gap-3 rounded-xl border border-surface-line bg-surface p-6"
            >
              <StepArt step={a.step} />
              <span className="font-display text-xl text-bone-quiet">{a.act}</span>
              <h3 className="m-0 text-[21px] font-semibold">{a.title}</h3>
              <p className="m-0 text-bone-muted">{a.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
