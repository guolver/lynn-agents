import { ManageShell } from '@/components/manage-shell';

export default function ManageLayout({ children }: { children: React.ReactNode }) {
  return <ManageShell>{children}</ManageShell>;
}
