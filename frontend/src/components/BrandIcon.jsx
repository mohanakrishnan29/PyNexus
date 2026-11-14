export default function BrandIcon({ size = 24, className = '' }) {
  return (
    <svg
      className={`brand-icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect x="4" y="4" width="12" height="12" rx="4" fill="#5b8def" />
      <rect x="16" y="16" width="12" height="12" rx="4" fill="#ffd84d" />
      <path d="M12 20C12 15.582 15.582 12 20 12" stroke="#e8edf7" strokeWidth="3" strokeLinecap="round" />
      <circle cx="10" cy="10" r="1.5" fill="#0a0a0a" />
      <circle cx="22" cy="22" r="1.5" fill="#0a0a0a" />
    </svg>
  )
}