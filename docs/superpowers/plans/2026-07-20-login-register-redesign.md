# Login/Register Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `frontend/app/login/page.tsx` and `frontend/app/register/page.tsx` to match the console's existing "Warm Stone + Amber Gold" design system, replacing the current unstyled plain-Tailwind forms.

**Architecture:** Two new presentational components (`AuthShell` for the card/branding chrome, `AuthInput` for icon+label inputs with password visibility toggle) shared by both pages. A new `── Auth Pages ──` CSS section in `app/globals.css` provides all styling, reusing existing CSS custom properties (`--ink`, `--amber`, `--surface`, `--line`, etc.) and the existing `jh-spin` keyframe for the loading spinner. Page components keep their existing state/fetch logic untouched and only change what they render.

**Tech Stack:** Next.js 16 (App Router), React 19, plain CSS (Tailwind's `@import` present but this design uses hand-written classes matching the rest of the app, not Tailwind utilities), Node's built-in `node:test` for the existing render-smoke-test suite.

**Design spec:** `docs/superpowers/specs/2026-07-20-login-register-redesign-design.md`

---

## File Structure

- **Modify:** `frontend/app/globals.css` — append `── Auth Pages ──` section with all new class names.
- **Create:** `frontend/components/auth-input.tsx` — labeled input with a leading icon (mail/lock) and, for password fields, a trailing show/hide toggle button. No page-specific logic.
- **Create:** `frontend/components/auth-shell.tsx` — the centered card: brand mark, brand name, subtitle, `children` (the form), and a `footer` slot (the "switch to other page" link line).
- **Modify:** `frontend/app/login/page.tsx` — swap the current inline markup for `AuthShell` + `AuthInput`, keep `handleSubmit`/state as-is.
- **Modify:** `frontend/app/register/page.tsx` — same swap, plus the existing password-length hint moves into `AuthInput`'s new `hint` prop.
- **Modify:** `frontend/tests/rendered-html.test.mjs` — add two render-smoke tests (`/login`, `/register`) asserting the new copy/markup is present.

---

## Task 1: Add Auth Pages CSS to globals.css

**Files:**
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Append the Auth Pages CSS section**

Add this to the end of `frontend/app/globals.css`:

```css

/* ── Auth Pages ── */

.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--bg);
}

.auth-card {
  width: 100%;
  max-width: 400px;
  padding: 40px 32px;
  border-radius: 14px;
  background: var(--surface);
  box-shadow: var(--shadow-lg);
}

.auth-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  margin-bottom: 28px;
}

.auth-brand-mark {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: var(--ink);
  color: var(--amber);
  font: 750 15px/1 var(--font-geist-mono);
}

.auth-brand-name {
  margin-top: 12px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.auth-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--ink-soft);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.auth-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.auth-label {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.auth-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.auth-input-icon {
  position: absolute;
  left: 12px;
  display: flex;
  color: var(--ink-soft);
  pointer-events: none;
}

.auth-input {
  width: 100%;
  padding: 10px 12px 10px 38px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--ink);
  font-size: 14px;
  transition: 150ms ease;
}

.auth-input::placeholder {
  color: var(--ink-soft);
}

.auth-input:focus {
  outline: none;
  border-color: var(--line-strong);
  box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.08);
}

.auth-input-password {
  padding-right: 38px;
}

.auth-toggle-visibility {
  position: absolute;
  right: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--ink-soft);
  cursor: pointer;
  border-radius: 6px;
  transition: 150ms ease;
}

.auth-toggle-visibility:hover {
  color: var(--ink);
  background: var(--bg-alt);
}

.auth-hint {
  margin: 0;
  font-size: 12px;
  color: var(--ink-soft);
}

.auth-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--red-soft);
  color: var(--red);
  font-size: 13px;
  line-height: 1.5;
}

.auth-error svg {
  flex-shrink: 0;
  margin-top: 1px;
}

.auth-submit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 11px;
  border: none;
  border-radius: 10px;
  background: var(--ink);
  color: var(--amber);
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
  transition: 150ms ease;
}

.auth-submit:hover:not(:disabled) {
  background: #292524;
}

.auth-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.auth-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(251, 191, 36, 0.35);
  border-top-color: var(--amber);
  border-radius: 50%;
  animation: jh-spin 0.8s linear infinite;
}

.auth-footer {
  margin-top: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--ink-soft);
}

.auth-footer-link {
  color: var(--amber-deep);
  text-decoration: underline;
  text-underline-offset: 2px;
  font-weight: 600;
}

.auth-footer-link:hover {
  color: #78350f;
}
```

This reuses the `jh-spin` `@keyframes` already defined earlier in the same file — CSS keyframe references don't require source order, so this is safe to append at the end.

- [ ] **Step 2: Commit**

```bash
cd frontend
git add app/globals.css
git commit -m "$(cat <<'EOF'
style(frontend): add Auth Pages CSS section

Prep work for redesigning the login/register pages to match the
console's Warm Stone + Amber Gold design system instead of plain
unstyled Tailwind.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create shared AuthInput component

**Files:**
- Create: `frontend/components/auth-input.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/components/auth-input.tsx`:

```tsx
'use client';

import { useId, useState } from 'react';

const MAIL_ICON = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="4" width="20" height="16" rx="2" />
    <path d="m22 7-10 5L2 7" />
  </svg>
);

const LOCK_ICON = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="11" rx="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);

const EYE_ICON = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const EYE_OFF_ICON = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 7 11 7a13.16 13.16 0 0 1-1.67 2.68M6.61 6.61C3.35 8.36 1 12 1 12s4 7 11 7a9.26 9.26 0 0 0 5.39-1.61" />
    <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
    <path d="M1 1l22 22" />
  </svg>
);

interface AuthInputProps {
  label: string;
  variant: 'email' | 'password';
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  required?: boolean;
  minLength?: number;
  autoComplete?: string;
  hint?: string;
}

export function AuthInput({
  label,
  variant,
  value,
  onChange,
  placeholder,
  required,
  minLength,
  autoComplete,
  hint,
}: AuthInputProps) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const isPassword = variant === 'password';
  const inputType = isPassword ? (visible ? 'text' : 'password') : 'email';

  return (
    <div className="auth-field">
      <label htmlFor={id} className="auth-label">
        {label}
      </label>
      <div className="auth-input-wrap">
        <span className="auth-input-icon">{isPassword ? LOCK_ICON : MAIL_ICON}</span>
        <input
          id={id}
          type={inputType}
          required={required}
          minLength={minLength}
          autoComplete={autoComplete}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className={`auth-input${isPassword ? ' auth-input-password' : ''}`}
        />
        {isPassword && (
          <button
            type="button"
            className="auth-toggle-visibility"
            onClick={() => setVisible((prev) => !prev)}
            aria-label={visible ? '隐藏密码' : '显示密码'}
          >
            {visible ? EYE_OFF_ICON : EYE_ICON}
          </button>
        )}
      </div>
      {hint && <p className="auth-hint">{hint}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Lint**

```bash
cd frontend
pnpm lint
```

Expected: no errors reported for `components/auth-input.tsx`.

- [ ] **Step 3: Commit**

```bash
cd frontend
git add components/auth-input.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): add shared AuthInput component

Icon-prefixed input with a show/hide toggle for password fields,
shared by the login and register pages.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Create shared AuthShell component

**Files:**
- Create: `frontend/components/auth-shell.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/components/auth-shell.tsx`:

```tsx
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
```

- [ ] **Step 2: Lint**

```bash
cd frontend
pnpm lint
```

Expected: no errors reported for `components/auth-shell.tsx`.

- [ ] **Step 3: Commit**

```bash
cd frontend
git add components/auth-shell.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): add shared AuthShell component

Centered card chrome (brand mark, name, subtitle, footer slot)
shared by the login and register pages.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Redesign the login page

**Files:**
- Modify: `frontend/app/login/page.tsx`
- Modify: `frontend/tests/rendered-html.test.mjs`

- [ ] **Step 1: Add a failing render-smoke test for `/login`**

Append this test to `frontend/tests/rendered-html.test.mjs` (after the existing tests, before end of file):

```js
test("server-renders the redesigned login page", async () => {
  const response = await render("/login");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /登录以继续使用 Agent Hub/);
  assert.match(html, /显示密码/);
  assert.match(html, /去注册/);
});
```

- [ ] **Step 2: Run the test suite and confirm it fails**

```bash
cd frontend
pnpm test
```

Expected: FAIL — the new test can't find "登录以继续使用 Agent Hub" or "显示密码" because `app/login/page.tsx` hasn't been redesigned yet. All pre-existing tests should still pass.

- [ ] **Step 3: Rewrite the login page**

Replace the full contents of `frontend/app/login/page.tsx`:

```tsx
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
```

- [ ] **Step 4: Run the test suite and confirm it passes**

```bash
cd frontend
pnpm test
```

Expected: PASS — all tests including the new `/login` test.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add app/login/page.tsx tests/rendered-html.test.mjs
git commit -m "$(cat <<'EOF'
feat(frontend): redesign login page to match console design system

Replaces the unstyled plain-Tailwind form with the AuthShell/AuthInput
components — centered card, icon-prefixed inputs, password visibility
toggle, and alert-style error messaging consistent with the rest of
the console.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Redesign the register page

**Files:**
- Modify: `frontend/app/register/page.tsx`
- Modify: `frontend/tests/rendered-html.test.mjs`

- [ ] **Step 1: Add a failing render-smoke test for `/register`**

Append this test to `frontend/tests/rendered-html.test.mjs`:

```js
test("server-renders the redesigned register page", async () => {
  const response = await render("/register");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /创建账号，开始使用 Agent Hub/);
  assert.match(html, /密码至少需要 8 位/);
  assert.match(html, /去登录/);
});
```

- [ ] **Step 2: Run the test suite and confirm it fails**

```bash
cd frontend
pnpm test
```

Expected: FAIL — the new test can't find "创建账号，开始使用 Agent Hub" or "密码至少需要 8 位" because `app/register/page.tsx` hasn't been redesigned yet. All other tests (including the `/login` one from Task 4) should still pass.

- [ ] **Step 3: Rewrite the register page**

Replace the full contents of `frontend/app/register/page.tsx`:

```tsx
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

export default function RegisterPage() {
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
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: '注册失败' }));
        setError(body.detail ?? '注册失败');
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
      subtitle="创建账号，开始使用 Agent Hub"
      footer={
        <>
          已有账号？
          <Link href="/login" className="auth-footer-link">
            去登录
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
          minLength={8}
          autoComplete="new-password"
          hint="密码至少需要 8 位"
        />
        {error && (
          <div className="auth-error" role="alert">
            {ALERT_ICON}
            <span>{error}</span>
          </div>
        )}
        <button type="submit" disabled={submitting} className="auth-submit">
          {submitting && <span className="auth-spinner" />}
          {submitting ? '注册中…' : '注册'}
        </button>
      </form>
    </AuthShell>
  );
}
```

- [ ] **Step 4: Run the test suite and confirm it passes**

```bash
cd frontend
pnpm test
```

Expected: PASS — all tests including the new `/login` and `/register` tests.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add app/register/page.tsx tests/rendered-html.test.mjs
git commit -m "$(cat <<'EOF'
feat(frontend): redesign register page to match console design system

Same AuthShell/AuthInput treatment as the login page, with the
existing 8-character password hint moved into AuthInput's hint slot.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full lint pass**

```bash
cd frontend
pnpm lint
```

Expected: no errors.

- [ ] **Step 2: Full test suite**

```bash
cd frontend
pnpm test
```

Expected: PASS — every test in `tests/rendered-html.test.mjs`, including the two new ones.

- [ ] **Step 3: Manual browser check**

Start the dev server and visually confirm both pages in a browser (centered card, icons in inputs, password toggle works, error state shows red alert bar, submit button shows spinner while submitting):

```bash
cd frontend
pnpm dev
```

Visit `http://localhost:3000/login` and `http://localhost:3000/register`. Stop the dev server (Ctrl-C) when done — do not commit anything from this step, it's verification only.
