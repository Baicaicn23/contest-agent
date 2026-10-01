// 手写 SVG 线性图标集（M8 侧栏复刻）：替代此前的文字图标。
// 统一规格：24 viewBox / 1.6 线宽 / currentColor（随文字变色）/ round 端点，
// 与竞品的细线图标风格对齐。全部是几何图形，不违反"无 emoji"规范。
const base = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
}

export const PlusCircleIcon = () => (
  <svg {...base}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8.5v7M8.5 12h7" />
  </svg>
)

export const SearchIcon = () => (
  <svg {...base}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M20 20l-4.4-4.4" />
  </svg>
)

export const ClockIcon = () => (
  <svg {...base}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5V12l3 2" />
  </svg>
)

export const GridIcon = () => (
  <svg {...base}>
    <rect x="4" y="4" width="7" height="7" rx="1.5" />
    <rect x="13" y="4" width="7" height="7" rx="1.5" />
    <rect x="4" y="13" width="7" height="7" rx="1.5" />
    <path d="M16.5 13.5v6M13.5 16.5h6" />
  </svg>
)

export const FolderIcon = ({ open = false }) => (
  <svg {...base}>
    {open
      ? <path d="M3.5 7.5v10a2 2 0 0 0 2 2h13.6a1.5 1.5 0 0 0 1.45-1.1l1.3-5a1.2 1.2 0 0 0-1.16-1.5H8.2a2 2 0 0 0-1.93 1.47L5 19M3.5 7.5v-1a2 2 0 0 1 2-2h3.6l2 2.5h7.4a2 2 0 0 1 2 2v1" />
      : <path d="M3.5 6.5v11a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-7l-2-2.5h-4a2 2 0 0 0-2 1.5z" />}
  </svg>
)

export const ChevronDownIcon = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}>
    <path d="M6.5 9.5l5.5 5.5 5.5-5.5" />
  </svg>
)

export const FilterIcon = () => (
  <svg {...base}>
    <path d="M4.5 7h15M7 12h10M10 17h4" />
  </svg>
)

export const TrashIcon = () => (
  <svg {...base}>
    <path d="M4.5 6.5h15M9.5 6.5v-1a1.5 1.5 0 0 1 1.5-1.5h2a1.5 1.5 0 0 1 1.5 1.5v1M6.5 6.5l1 12a2 2 0 0 0 2 1.8h5a2 2 0 0 0 2-1.8l1-12M10 10.5v6M14 10.5v6" />
  </svg>
)

export const PlusIcon = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}>
    <path d="M12 5.5v13M5.5 12h13" />
  </svg>
)

export const GearIcon = () => (
  <svg {...base}>
    <circle cx="12" cy="12" r="3.2" />
    <path d="M12 3.5l1 2.3 2.5-.6 1.2 2.2 2.3 1-.6 2.5 1.6 1.9-1.6 1.9.6 2.5-2.3 1-1.2 2.2-2.5-.6-1 2.3-1-2.3-2.5.6-1.2-2.2-2.3-1 .6-2.5L3.4 12 5 10.1l-.6-2.5 2.3-1 1.2-2.2 2.5.6z" />
  </svg>
)

export const PanelIcon = () => (
  // 侧栏折叠：左面板 + 分隔线（竞品同款）
  <svg {...base}>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
    <path d="M9.5 4.5v15" />
    <path d="M6 8.5h1.5M6 11.5h1.5" />
  </svg>
)

export const SpinnerIcon = ({ size = 13 }) => (
  // 运行中转圈：旋转动画在 CSS（.icon-spinner），这里只画弧
  <svg {...base} width={size} height={size} className="icon-spinner">
    <path d="M12 4.5a7.5 7.5 0 1 0 7.5 7.5" />
  </svg>
)

export const CheckIcon = ({ size = 13 }) => (
  <svg {...base} width={size} height={size}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
)

export const XSmallIcon = ({ size = 12 }) => (
  <svg {...base} width={size} height={size}>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)

export const ShieldIcon = ({ size = 13 }) => (
  <svg {...base} width={size} height={size}>
    <path d="M12 3.5l7 2.6v5.2c0 4.4-3 7.6-7 9.2-4-1.6-7-4.8-7-9.2V6.1z" />
    <path d="M12 8v4" />
  </svg>
)

export const FileIcon = ({ size = 12 }) => (
  <svg {...base} width={size} height={size}>
    <path d="M6.5 3.5h7l4 4v13h-11zM13.5 3.5v4h4" />
  </svg>
)
