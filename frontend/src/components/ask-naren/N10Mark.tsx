/** The product name, in one place, so a rename is one edit. */
export const PRODUCT_NAME = 'N10';

/**
 * The N10 mark: a bold N on Joveo indigo with a gold "10" score badge in the corner -- "Naren is
 * a 10 on 10" (option B, chosen 2026-11-10). Fixed brand colours, not theme tokens: a logo
 * looks the same in light and dark mode.
 *
 * Decorative by default, because it always sits beside the product name or an answer that
 * already says what it is. Pass `label` where it stands alone.
 */
export function N10Mark({ size = 28, label }: { size?: number; label?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      className="shrink-0"
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
    >
      <rect width="40" height="40" rx="11" fill="#5454BF" />
      <path
        d="M11 30V14l14 16V14"
        fill="none"
        stroke="#FFFFFF"
        strokeWidth="3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="31" cy="10" r="8.5" fill="#D09247" stroke="#5454BF" strokeWidth="2" />
      <text x="31" y="13.3" textAnchor="middle" fontSize="9" fontWeight="800" fill="#1D1D45">
        10
      </text>
    </svg>
  );
}
