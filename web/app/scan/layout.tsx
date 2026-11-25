import { MotionProvider } from '@/components/ui/motion-provider';

export default function ScanLayout({ children }: { children: React.ReactNode }) {
  return <MotionProvider>{children}</MotionProvider>;
}
