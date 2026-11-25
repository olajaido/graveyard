import { MotionProvider } from '@/components/ui/motion-provider';

export default function GraveLayout({ children }: { children: React.ReactNode }) {
  return <MotionProvider>{children}</MotionProvider>;
}
