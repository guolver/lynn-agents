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
          aria-describedby={hint ? `${id}-hint` : undefined}
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
      {hint && (
        <p id={`${id}-hint`} className="auth-hint">
          {hint}
        </p>
      )}
    </div>
  );
}
