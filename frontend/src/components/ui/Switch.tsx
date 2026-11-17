import React from 'react';

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  size?: 'sm' | 'md' | 'lg';
  activeColor?: 'emerald' | 'pond' | 'indigo';
  label?: React.ReactNode;
  stateLabel?: {
    on: string;
    off: string;
  };
  className?: string;
  id?: string;
  'aria-label'?: string;
}

export function Switch({
  checked,
  onChange,
  disabled = false,
  size = 'md',
  activeColor = 'emerald',
  label,
  stateLabel,
  className = '',
  id,
  'aria-label': ariaLabel,
}: SwitchProps) {
  const isSm = size === 'sm';
  const isLg = size === 'lg';

  const colorStyles = {
    emerald: 'bg-emerald-500 hover:bg-emerald-600',
    pond: 'bg-[var(--accent-pond)] hover:bg-[var(--accent-pond-dark)]',
    indigo: 'bg-indigo-600 hover:bg-indigo-700',
  };

  const activeBg = colorStyles[activeColor] || colorStyles.emerald;
  const inactiveBg = 'bg-gray-300 dark:bg-zinc-700 hover:bg-gray-400 dark:hover:bg-zinc-600';

  const trackSizes = isSm ? 'h-5 w-9 p-0.5' : isLg ? 'h-7 w-13 p-1' : 'h-6 w-11 p-0.5';
  const thumbSizes = isSm
    ? `h-4 w-4 ${checked ? 'translate-x-4' : 'translate-x-0'}`
    : isLg
    ? `h-5 w-5 ${checked ? 'translate-x-6' : 'translate-x-0'}`
    : `h-5 w-5 ${checked ? 'translate-x-5' : 'translate-x-0'}`;

  return (
    <div className={`inline-flex items-center gap-2.5 select-none ${className}`}>
      {stateLabel && (
        <span
          className={`text-xs font-semibold tracking-tight transition-colors ${
            checked
              ? 'text-emerald-600 dark:text-emerald-400 font-bold'
              : 'text-[var(--text-muted)]'
          }`}
        >
          {checked ? stateLabel.on : stateLabel.off}
        </span>
      )}
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative inline-flex shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 ${trackSizes} ${
          checked ? activeBg : inactiveBg
        } ${disabled ? 'opacity-50 cursor-not-allowed' : 'active:scale-95'}`}
      >
        <span
          className={`pointer-events-none inline-block rounded-full bg-white shadow-sm ring-0 transition-transform duration-200 ease-in-out ${thumbSizes}`}
        />
      </button>
      {label && <span className="text-xs text-[var(--text-secondary)]">{label}</span>}
    </div>
  );
}

