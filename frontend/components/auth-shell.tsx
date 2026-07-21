import type { ReactNode } from 'react';

interface AuthShellProps {
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}

export function AuthShell({ subtitle, children, footer }: AuthShellProps) {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="auth-brand-mark">AH</span>
          <span className="auth-brand-name">Agent Hub</span>
          <p className="auth-subtitle">{subtitle}</p>
        </div>
        {children}
        <div className="auth-footer">{footer}</div>
      </div>
    </div>
  );
}
