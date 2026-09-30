// 品牌标志：橙色米字花（对应截图左上角与问候语旁的 asterisk）。
// 用 SVG 手绘 12 根辐条，颜色跟 currentColor 走——外层给 .logo 类即品牌橙。
export default function Logo({ size = 24, className = '' }) {
  const spokes = []
  for (let i = 0; i < 12; i++) {
    const angle = (i * 30 * Math.PI) / 180
    const x1 = 12 + Math.cos(angle) * 3.2
    const y1 = 12 + Math.sin(angle) * 3.2
    const x2 = 12 + Math.cos(angle) * 10.5
    const y2 = 12 + Math.sin(angle) * 10.5
    spokes.push(
      <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
    )
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24"
         className={className} aria-hidden="true">
      {spokes}
    </svg>
  )
}
