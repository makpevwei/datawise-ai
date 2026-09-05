import type { SVGProps } from "react";

/**
 * Hand-authored outline icon set -- no icon library dependency, consistent
 * with charts.tsx's fully-custom SVG approach elsewhere in this app. Every
 * icon shares a 24x24 viewBox, 1.75px stroke, round joins, and inherits
 * `currentColor` so it always follows the surrounding text/brand color.
 *
 * Added as part of the design-system pass -- before this, the app had no
 * icon anywhere, which was one of the clearest "template" tells reviewed
 * in that pass (see plan file). Icons are used sparingly: nav items,
 * section headings, empty states, and a handful of trust/status badges --
 * never decoratively on every line.
 */

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base(props: IconProps) {
  const { size = 18, ...rest } = props;
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    ...rest,
  };
}

export function IconLayoutDashboard(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  );
}

export function IconSparkles(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M11 3.5 12.6 8l4.4 1.6-4.4 1.6L11 15.7l-1.6-4.5L5 9.6l4.4-1.6L11 3.5Z" />
      <path d="M18.2 15.5 19 17.7l2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" />
    </svg>
  );
}

export function IconDatabase(props: IconProps) {
  return (
    <svg {...base(props)}>
      <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
      <path d="M4.5 5.5v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-6" />
      <path d="M4.5 11.5v6c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-6" />
    </svg>
  );
}

export function IconClock(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

export function IconFileText(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6.5 3h7.2L18 6.6V21h-11.5Z" />
      <path d="M13.5 3v3.8h3.7" />
      <path d="M9 12.5h6M9 16h6M9 9h2.5" />
    </svg>
  );
}

export function IconTrendingUp(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3.5 17 9.5 11l3.5 3.5 7-7.5" />
      <path d="M15.5 6.5H20V11" />
    </svg>
  );
}

export function IconChartBar(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 20V10M11 20V4M18 20v-7" />
    </svg>
  );
}

export function IconLink(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 6.5 12.5 5a3.9 3.9 0 0 1 5.5 5.5L16.5 12" />
      <path d="M13 17.5 11.5 19A3.9 3.9 0 0 1 6 13.5L7.5 12" />
    </svg>
  );
}

export function IconGear(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2M12 18.5v2M20.5 12h-2M5.5 12h-2M17.8 6.2l-1.4 1.4M7.6 16.4l-1.4 1.4M17.8 17.8l-1.4-1.4M7.6 7.6 6.2 6.2" />
    </svg>
  );
}

export function IconUploadCloud(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M7.5 17.5A4.5 4.5 0 0 1 8 8.6a5.5 5.5 0 0 1 10.6 1.9A4 4 0 0 1 18 17.5Z" />
      <path d="M12 20v-7.5M9 15l3-3 3 3" />
    </svg>
  );
}

export function IconCheckCircle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12.3 11 14.8l4.7-5.6" />
    </svg>
  );
}

export function IconAlertTriangle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 4.2 21 19.5H3Z" />
      <path d="M12 10v4M12 16.7v.1" />
    </svg>
  );
}

export function IconShieldCheck(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3.5 19 6v6c0 4.5-3 7.5-7 8.5-4-1-7-4-7-8.5V6Z" />
      <path d="M9 12.2l2 2 4-4.4" />
    </svg>
  );
}

export function IconGlobe(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17M12 3.5a13 13 0 0 1 3.5 8.5A13 13 0 0 1 12 20.5 13 13 0 0 1 8.5 12 13 13 0 0 1 12 3.5Z" />
    </svg>
  );
}

export function IconLock(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="5.5" y="10.5" width="13" height="9.5" rx="1.75" />
      <path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3" />
    </svg>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconMenu(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 6.5h16M4 12h16M4 17.5h16" />
    </svg>
  );
}

export function IconX(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 4v11M8 11.5l4 4 4-4" />
      <path d="M5 18.5h14" />
    </svg>
  );
}

export function IconChevronDown(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function IconRefreshCw(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M20 8.5A8 8 0 0 0 5.5 6.2M4 15.5a8 8 0 0 0 14.5 2.3" />
      <path d="M19.5 4v4.5H15M4.5 20v-4.5H9" />
    </svg>
  );
}
