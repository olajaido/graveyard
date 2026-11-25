import { FenceStrip } from '@/components/art/fence-strip';

export function SiteFooter() {
  return (
    <footer className="relative overflow-hidden border-t border-hairline">
      <FenceStrip className="block h-[60px] w-full" />
      <div className="container-page flex flex-wrap justify-between gap-4 pb-8 pt-6 text-sm text-bone-quiet">
        <span>Built for Kiroween 2026 with Kiro.</span>
        <span className="font-display text-[17px] italic">Rest in peace, left-pad.</span>
      </div>
    </footer>
  );
}
