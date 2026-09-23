import { useCallback, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  resolveStyleText,
  type KpiDef,
  type KpiHealth,
  type TradeStyle,
} from './mytradeKpiHelp'

type Props = {
  def: KpiDef
  value: number | null
  health: KpiHealth
  formatted: string
  style: TradeStyle
}

type TipPos = { top: number; left: number }

const TIP_W = 280

export default function KpiCard({ def, value, health, formatted, style }: Props) {
  const btnRef = useRef<HTMLButtonElement>(null)
  const [tipPos, setTipPos] = useState<TipPos | null>(null)

  const good = resolveStyleText(def.good, style)
  const warn = resolveStyleText(def.warn, style)
  const bad = resolveStyleText(def.bad, style)
  const benchmark =
    health === 'good' ? good : health === 'warn' ? warn : health === 'bad' ? bad : def.description

  const placeTooltip = useCallback(() => {
    const el = btnRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    let left = r.right - TIP_W
    left = Math.max(12, Math.min(left, window.innerWidth - TIP_W - 12))
    let top = r.bottom + 8
    const approxH = 220
    if (top + approxH > window.innerHeight - 12) {
      top = Math.max(12, r.top - approxH - 8)
    }
    setTipPos({ top, left })
  }, [])

  const hideTooltip = useCallback(() => setTipPos(null), [])

  const tooltip =
    tipPos &&
    createPortal(
      <div
        className="mt-kpi-tooltip mt-kpi-tooltip-portal"
        role="tooltip"
        style={{ top: tipPos.top, left: tipPos.left }}
        onMouseEnter={placeTooltip}
        onMouseLeave={hideTooltip}
      >
        <p className="mt-kpi-tip-desc">{def.description}</p>
        <div className="mt-kpi-tip-bench">
          <span className="good">✓ Good: {good}</span>
          <span className="warn">⚠ Okay: {warn}</span>
          <span className="bad">✗ Bad: {bad}</span>
        </div>
        {value != null && (
          <p className="mt-kpi-tip-now">
            Your value: <strong>{formatted}</strong>
          </p>
        )}
      </div>,
      document.body,
    )

  return (
    <div className={`mt-kpi-card health-${health}${tipPos ? ' tip-open' : ''}`}>
      <div className="mt-kpi-card-head">
        <span className="mt-kpi-label">{def.label}</span>
        <button
          ref={btnRef}
          type="button"
          className="mt-kpi-info"
          aria-label={`About ${def.label}`}
          onMouseEnter={placeTooltip}
          onMouseLeave={hideTooltip}
          onFocus={placeTooltip}
          onBlur={hideTooltip}
        >
          ⓘ
        </button>
      </div>
      <div className={`mt-kpi-value ${health}`}>{formatted}</div>
      <div className="mt-kpi-benchmark">{benchmark}</div>
      {tooltip}
    </div>
  )
}
