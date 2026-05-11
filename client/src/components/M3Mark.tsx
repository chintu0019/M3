import type { CSSProperties } from "react";

type Variant = "canonical" | "constellation";

type Props = {
  size?: number | string;
  variant?: Variant;
  className?: string;
  style?: CSSProperties;
  title?: string;
};

export function M3Mark({
  size = 24,
  variant = "canonical",
  className,
  style,
  title = "M3",
}: Props) {
  const dim = typeof size === "number" ? `${size}px` : size;
  const showDescenders = variant === "canonical";
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 120 120"
      width={dim}
      height={dim}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.999}
      strokeLinecap="butt"
      strokeLinejoin="miter"
      role="img"
      aria-label={title}
      className={className}
      style={style}
    >
      <title>{title}</title>
      <g>
        {showDescenders && (
          <>
            <line x1="18.347" y1="27.802" x2="18.347" y2="99.445" />
            <line x1="101.653" y1="27.802" x2="101.653" y2="99.445" />
            <line x1="13.536" y1="99.445" x2="23.158" y2="99.445" />
            <line x1="96.842" y1="99.445" x2="106.464" y2="99.445" />
          </>
        )}
        {showDescenders ? (
          <>
            <line x1="18.347" y1="27.802" x2="60.000" y2="84.075" />
            <line x1="101.653" y1="27.802" x2="60.000" y2="84.075" />
          </>
        ) : (
          <>
            <line x1="18.347" y1="31.863" x2="60.000" y2="88.137" />
            <line x1="101.653" y1="31.863" x2="60.000" y2="88.137" />
          </>
        )}
      </g>
      <g fill="currentColor" stroke="none">
        {showDescenders ? (
          <>
            <circle cx="18.347" cy="27.802" r="8.747" />
            <circle cx="101.653" cy="27.802" r="8.747" />
            <circle cx="60.000" cy="84.075" r="8.747" />
          </>
        ) : (
          <>
            <circle cx="18.347" cy="31.863" r="8.747" />
            <circle cx="101.653" cy="31.863" r="8.747" />
            <circle cx="60.000" cy="88.137" r="8.747" />
          </>
        )}
      </g>
    </svg>
  );
}

export default M3Mark;
