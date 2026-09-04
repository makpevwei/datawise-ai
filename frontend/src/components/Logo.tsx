/**
 * DataWise AI's mark: three ascending bars (the data) with a small spark
 * at the peak (the AI reasoning layer on top of it) -- replaces the
 * previous plain-text-only wordmark used in the sidebar, mobile header,
 * and auth pages. Single brand color, no gradients -- reads clearly at
 * both the ~20px nav size and the larger auth-page size.
 */
export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <rect x="3" y="13" width="4.2" height="8" rx="1" fill="var(--brand)" opacity="0.55" />
      <rect x="9.9" y="8.5" width="4.2" height="12.5" rx="1" fill="var(--brand)" opacity="0.8" />
      <rect x="16.8" y="4.5" width="4.2" height="16.5" rx="1" fill="var(--brand)" />
      <path
        d="M15.6 3.4 16.4 5.3l1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8.8-1.9Z"
        fill="var(--brand)"
      />
    </svg>
  );
}

export function Logo({
  size = 22,
  withTagline = false,
}: {
  size?: number;
  withTagline?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <LogoMark size={size} />
      <div>
        <p className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">
          DataWise <span className="text-[var(--brand)]">AI</span>
        </p>
        {withTagline && (
          <p className="text-xs text-[var(--text-secondary)]">Your AI Business Analyst</p>
        )}
      </div>
    </div>
  );
}
