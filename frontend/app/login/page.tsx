'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { AuthShell } from '../../components/auth-shell';
import { AuthInput } from '../../components/auth-input';

const ALERT_ICON = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="8" x2="12" y2="12" />
    <line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>
);

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: '登录失败' }));
        setError(body.detail ?? '登录失败');
        setSubmitting(false);
        return;
      }
      router.push('/');
    } catch {
      setError('网络错误，请稍后重试');
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      subtitle="登录以继续使用 Agent Hub"
      footer={
        <>
          还没有账号？
          <Link href="/register" className="auth-footer-link">
            去注册
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="auth-form">
        <AuthInput
          label="邮箱"
          variant="email"
          value={email}
          onChange={setEmail}
          placeholder="邮箱"
          required
          autoComplete="email"
        />
        <AuthInput
          label="密码"
          variant="password"
          value={password}
          onChange={setPassword}
          placeholder="密码"
          required
          autoComplete="current-password"
        />
        {error && (
          <div className="auth-error" role="alert">
            {ALERT_ICON}
            <span>{error}</span>
          </div>
        )}
        <button type="submit" disabled={submitting} className="auth-submit">
          {submitting && <span className="auth-spinner" />}
          {submitting ? '登录中…' : '登录'}
        </button>
      </form>
    </AuthShell>
  );
}
