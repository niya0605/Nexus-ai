import type { SVGProps } from "react";

/**
 * A small, consistent line-icon set for the dashboard nav — 20x20,
 * 1.5px stroke, rounded caps. Hand-built rather than pulling in an icon
 * library, since only a handful are needed and consistency across them
 * matters more than variety.
 */

type IconProps = SVGProps<SVGSVGElement>;

const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function AskIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 3v3M12 18v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M3 12h3M18 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function DocumentsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="5" y="3" width="12" height="16" rx="1.5" />
      <path d="M9 8h4M9 12h4M9 16h2" />
    </svg>
  );
}

export function CollectionsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="4" width="8" height="8" rx="1.2" />
      <rect x="13" y="4" width="8" height="8" rx="1.2" />
      <rect x="3" y="14" width="8" height="6" rx="1.2" />
      <rect x="13" y="14" width="8" height="6" rx="1.2" />
    </svg>
  );
}

export function SummariesIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 6h16M4 12h10M4 18h13" />
    </svg>
  );
}

export function InsightsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 18h6M10 21h4M12 3a6 6 0 00-3 11.2c.5.3.8.9.8 1.5v.3h4.4v-.3c0-.6.3-1.2.8-1.5A6 6 0 0012 3z" />
    </svg>
  );
}

export function ActivityIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </svg>
  );
}

export function MembersIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5.1a3 3 0 010 5.8M20 19.5c-.2-2.5-1.6-4.4-3.5-5.3" />
    </svg>
  );
}

export function IntegrationsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 3v4M15 3v4M9 17v4M15 17v4M5 9H1M5 15H1M23 9h-4M23 15h-4" />
      <rect x="5" y="7" width="14" height="10" rx="2" />
    </svg>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 13a7.7 7.7 0 000-2l2-1.5-2-3.4-2.3.9a7.6 7.6 0 00-1.8-1l-.3-2.5H9.9l-.3 2.5a7.6 7.6 0 00-1.8 1l-2.3-.9-2 3.4L5.5 11a7.7 7.7 0 000 2l-2 1.5 2 3.4 2.3-.9c.5.4 1.1.8 1.8 1l.3 2.5h4.9l.3-2.5a7.6 7.6 0 001.8-1l2.3.9 2-3.4-2-1.5z" />
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </svg>
  );
}

export function SendIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 12l16-8-6 16-3-7-7-1z" />
    </svg>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function UploadIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
    </svg>
  );
}

export function FlameIcon(props: IconProps) {
  return (
    <svg {...base} {...props} fill="var(--accent)" stroke="none">
      <path d="M12 2c1 4-3 5-3 9a3 3 0 006 0c0-1-1-2-1-2 2 1 3 3 3 5a5 5 0 01-10 0c0-5 3-6 5-12z" />
    </svg>
  );
}

export function BadgeIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 2l7 3v6c0 5-3 8.5-7 10-4-1.5-7-5-7-10V5l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

export function ShieldIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 2l7 3v6c0 5-3 8.5-7 10-4-1.5-7-5-7-10V5l7-3z" />
    </svg>
  );
}

export function LevelUpIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 20V6M6 12l6-6 6 6" />
    </svg>
  );
}

export function PlayIcon(props: IconProps) {
  return (
    <svg {...base} {...props} fill="currentColor" stroke="none">
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  );
}

export function ChartIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 20V10M10 20V4M16 20v-7M4 20h16" />
    </svg>
  );
}

export function ImageIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="1.6" />
      <path d="M4 17l5-5 4 4 3-3 4 4" />
    </svg>
  );
}

export function SpreadsheetIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="4" y="4" width="16" height="16" rx="1.5" />
      <path d="M4 10h16M4 15h16M10 4v16" />
    </svg>
  );
}

export function PresentationIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="4" width="18" height="12" rx="1.5" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}

export function TextDocIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4M9 12h6M9 16h6" />
    </svg>
  );
}

export function BellIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M6 10a6 6 0 0112 0c0 4 1.5 5.5 2 6.5H4c.5-1 2-2.5 2-6.5Z" />
      <path d="M10 20a2 2 0 004 0" />
    </svg>
  );
}

export function SlidersIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M5 6h6M15 6h4M5 12h10M19 12h0M5 18h2M11 18h8" />
      <circle cx="13" cy="6" r="2" />
      <circle cx="17" cy="12" r="2" />
      <circle cx="9" cy="18" r="2" />
    </svg>
  );
}

export function SparkleIcon(props: IconProps) {
  return (
    <svg {...base} {...props} fill="currentColor" stroke="none">
      <path d="M12 2l1.8 5.6L19.5 9l-5.7 1.4L12 16l-1.8-5.6L4.5 9l5.7-1.4z" />
    </svg>
  );
}

export function ExternalLinkIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 6H5a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-4M14 3h7v7M21 3l-9 9" />
    </svg>
  );
}

export function DownloadIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 3v12M7 10l5 5 5-5M4 19h16" />
    </svg>
  );
}

export function ThumbUpIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M7 11v9M3 12v6a2 2 0 002 2h2M7 11l3-7a2 2 0 012 2v4h6a2 2 0 012 2l-1.5 6a2 2 0 01-2 1.5H9" />
    </svg>
  );
}

export function ThumbDownIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M17 13V4M21 12V6a2 2 0 00-2-2h-2M17 13l-3 7a2 2 0 01-2-2v-4H6a2 2 0 01-2-2l1.5-6A2 2 0 017.5 4H15" />
    </svg>
  );
}

export function CommentIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 5h16v11H8l-4 4z" />
    </svg>
  );
}
