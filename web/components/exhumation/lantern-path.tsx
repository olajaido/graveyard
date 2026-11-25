import { Lantern, type LanternState } from '@/components/art/lantern';
import { LANTERNS, type LanternStatus } from '@/lib/model/stage-map';
import type { Progress, Service } from '@/lib/api/types';

const STATUS_WORD: Record<LanternStatus, string> = {
  done: 'done',
  working: 'working',
  waiting: 'waiting',
  stopped: 'stopped',
};
const STATUS_COLOR: Record<LanternStatus, string> = {
  done: 'text-alive',
  working: 'text-ailing',
  waiting: 'text-bone-dim',
  stopped: 'text-dead',
};
const ART: Record<LanternStatus, LanternState> = {
  done: 'lit',
  working: 'working',
  waiting: 'unlit',
  stopped: 'unlit',
};

/** Facts only: a caption is a description of the step, or a number the API returned. */
export function captions(services: Service[] | null, progress: Progress | null): string[] {
  const lockfiles = services?.reduce((n, s) => n + s.manifests.length, 0);
  return [
    'public repository',
    lockfiles === undefined
      ? 'the lockfiles'
      : `${lockfiles} lockfile${lockfiles === 1 ? '' : 's'} dug up`,
    'package inventory',
    'who brought whom',
    progress ? `${progress.examined} of ${progress.total} examined` : 'the bodies',
    'final states',
  ];
}

/** The six lanterns. The word beside each one says its state, so colour is never the only signal. */
export function LanternPath({
  statuses,
  services,
  progress,
}: {
  statuses: LanternStatus[];
  services: Service[] | null;
  progress: Progress | null;
}) {
  const notes = captions(services, progress);
  return (
    <ol className="relative m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3 p-0">
      {LANTERNS.map((name, i) => {
        const status = statuses[i] ?? 'waiting';
        return (
          <li
            key={name}
            aria-current={status === 'working' ? 'step' : undefined}
            className="flex flex-col items-center gap-2 text-center"
          >
            <Lantern state={ART[status]} />
            <span
              className={`font-semibold ${status === 'working' ? 'text-flame' : status === 'waiting' ? 'text-bone-muted' : ''}`}
            >
              {name}
            </span>
            <span className="text-[13px] text-bone-soft">{notes[i]}</span>
            <span className={`text-xs ${STATUS_COLOR[status]}`}>{STATUS_WORD[status]}</span>
          </li>
        );
      })}
    </ol>
  );
}
