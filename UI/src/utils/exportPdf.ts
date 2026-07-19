import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import type { HorizonOutlook, StockAnalysis } from '../api/client'

const GREEN: [number, number, number] = [0, 179, 134]
const GREEN_DARK: [number, number, number] = [0, 160, 120]
const DARK: [number, number, number] = [25, 28, 31]
const MUTED: [number, number, number] = [124, 126, 140]
const RED: [number, number, number] = [235, 91, 60]
const LIGHT: [number, number, number] = [245, 247, 246]

const MARGIN = 40

const METRIC_LABELS: Record<string, string> = {
  close: 'Last Price (Rs)',
  change_pct: 'Change %',
  return_1w_pct: '1W Return %',
  return_1m_pct: '1M Return %',
  return_3m_pct: '3M Return %',
  return_6m_pct: '6M Return %',
  return_1y_pct: '1Y Return %',
  rsi: 'RSI (14)',
  adx: 'ADX',
  atr: 'ATR',
  ema_20: 'EMA 20',
  ema_50: 'EMA 50',
  ema_200: 'EMA 200',
  high_52w: '52W High',
  low_52w: '52W Low',
  dist_52w_high_pct: 'Below 52W High %',
  volume_ratio: 'Volume Ratio',
  avg_daily_volume: 'Avg Daily Volume',
  ema_aligned_bull: 'EMA Bull Aligned',
  near_20d_breakout: 'Near 20D Breakout',
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function verdictColor(v?: string): [number, number, number] {
  const b = (v || '').toLowerCase()
  if (b.includes('buy') || b.includes('accumulate') || b.includes('bull') || b.includes('positive') || b.includes('strong'))
    return GREEN
  if (b.includes('avoid') || b.includes('reduce') || b.includes('sell') || b.includes('bear') || b.includes('negative') || b.includes('weak'))
    return RED
  return MUTED
}

function lastY(doc: jsPDF): number {
  const d = doc as unknown as { lastAutoTable?: { finalY: number } }
  return d.lastAutoTable?.finalY ?? MARGIN
}

export function exportStockReportPdf(analysis: StockAnalysis): void {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const report = analysis.report || {}

  // ── Brand header band ──────────────────────────────────────────
  doc.setFillColor(...GREEN)
  doc.rect(0, 0, pageW, 70, 'F')
  // Logo mark
  doc.setFillColor(255, 255, 255)
  doc.roundedRect(MARGIN, 22, 26, 26, 6, 6, 'F')
  doc.setTextColor(...GREEN_DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.text('T', MARGIN + 13, 40, { align: 'center' })
  // Wordmark + TM
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(20)
  doc.text('TRADELE', MARGIN + 38, 38)
  doc.setFontSize(8)
  doc.text('TM', MARGIN + 38 + doc.getTextWidth('TRADELE') + 3, 30)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text('AI Trading Intelligence', MARGIN + 38, 52)
  // Right: report label
  doc.setFontSize(9)
  doc.text('Equity Research Report', pageW - MARGIN, 34, { align: 'right' })
  doc.text(`Generated: ${analysis.generated_at || ''}`, pageW - MARGIN, 48, { align: 'right' })

  let y = 96

  // ── Title row ──────────────────────────────────────────────────
  doc.setTextColor(...DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(18)
  doc.text(analysis.company || analysis.symbol, MARGIN, y)

  // Verdict pill (right)
  const vColor = verdictColor(report.verdict)
  const pillW = 150
  const pillX = pageW - MARGIN - pillW
  doc.setFillColor(...vColor)
  doc.roundedRect(pillX, y - 20, pillW, 44, 6, 6, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(15)
  doc.setFont('helvetica', 'bold')
  doc.text((report.verdict || 'HOLD').toUpperCase(), pillX + pillW / 2, y - 2, { align: 'center' })
  if (typeof report.conviction === 'number') {
    doc.setFontSize(8)
    doc.setFont('helvetica', 'normal')
    doc.text(`${report.conviction}% conviction`, pillX + pillW / 2, y + 14, { align: 'center' })
  }

  y += 18
  doc.setTextColor(...MUTED)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  const sub = [analysis.symbol, analysis.sector && analysis.sector !== 'Unknown' ? analysis.sector : null]
    .filter(Boolean)
    .join('  |  ')
  doc.text(sub, MARGIN, y)
  doc.setTextColor(...DARK)
  doc.setFont('helvetica', 'bold')
  const priceStr = `Rs ${fmt(analysis.metrics?.close)}   (${Number(analysis.metrics?.change_pct) >= 0 ? '+' : ''}${fmt(analysis.metrics?.change_pct)}%)`
  doc.text(priceStr, MARGIN + doc.getTextWidth(sub) + 16, y)

  y += 18

  // ── Executive summary ──────────────────────────────────────────
  if (report.summary) {
    doc.setDrawColor(...GREEN)
    doc.setLineWidth(3)
    doc.line(MARGIN, y - 2, MARGIN, y + 30)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(10)
    doc.setTextColor(...DARK)
    const lines = doc.splitTextToSize(report.summary, pageW - 2 * MARGIN - 12)
    doc.text(lines, MARGIN + 12, y + 8)
    y += 12 + lines.length * 13
  }

  // ── Outlook table ──────────────────────────────────────────────
  const o = report.outlook || {}
  const row = (label: string, h?: HorizonOutlook) => [
    label,
    h?.bias || '-',
    h?.expected_range || '-',
    typeof h?.confidence === 'number' ? `${h.confidence}%` : '-',
    h?.rationale || '-',
  ]
  autoTable(doc, {
    startY: y + 8,
    head: [['Horizon', 'Bias', 'Expected Range', 'Conf.', 'Rationale']],
    body: [
      row('Next Week', o.next_week),
      row('Next Month', o.next_month),
      row('Next 3 Months', o.next_3_months),
    ],
    theme: 'grid',
    headStyles: { fillColor: GREEN, textColor: 255, fontStyle: 'bold', fontSize: 9 },
    styles: { fontSize: 8.5, cellPadding: 5, textColor: DARK, valign: 'top' },
    columnStyles: {
      0: { fontStyle: 'bold', cellWidth: 70 },
      1: { cellWidth: 52 },
      2: { cellWidth: 95 },
      3: { cellWidth: 34, halign: 'center' },
      4: { cellWidth: 'auto' },
    },
    margin: { left: MARGIN, right: MARGIN },
    didParseCell: (data) => {
      if (data.section === 'body' && data.column.index === 1) {
        data.cell.styles.textColor = verdictColor(String(data.cell.raw))
        data.cell.styles.fontStyle = 'bold'
      }
    },
  })
  y = lastY(doc) + 20

  sectionTitle(doc, 'Outlook', y - 20 - 8)

  // ── Trade plan ─────────────────────────────────────────────────
  const e = report.entry
  if (e) {
    sectionTitle(doc, 'Trade Plan', y)
    autoTable(doc, {
      startY: y + 8,
      head: [['Buy Zone', 'Stop Loss', 'Target 1', 'Target 2', 'Risk / Reward']],
      body: [[
        e.buy_zone || '-',
        e.stop_loss != null ? `Rs ${fmt(e.stop_loss)}` : '-',
        e.target_1 != null ? `Rs ${fmt(e.target_1)}` : '-',
        e.target_2 != null ? `Rs ${fmt(e.target_2)}` : '-',
        e.risk_reward || '-',
      ]],
      theme: 'grid',
      headStyles: { fillColor: DARK, textColor: 255, fontStyle: 'bold', fontSize: 9 },
      styles: { fontSize: 9, cellPadding: 6, halign: 'center', textColor: DARK },
      margin: { left: MARGIN, right: MARGIN },
    })
    y = lastY(doc) + 20
  }

  // ── Analysis sections ──────────────────────────────────────────
  y = analysisBlock(doc, 'Fundamental Analysis', report.fundamental?.rating, report.fundamental?.points, report.fundamental?.risks, y)
  y = analysisBlock(doc, 'Technical Analysis', report.technical?.trend || report.technical?.rating, report.technical?.points, undefined, y, report.technical?.key_levels)
  y = analysisBlock(
    doc,
    'Sentiment Analysis',
    report.sentiment?.rating,
    report.sentiment?.points,
    undefined,
    y,
    undefined,
    report.sentiment?.industry_impact,
  )

  // ── Catalysts / Red flags ──────────────────────────────────────
  if (report.catalysts?.length || report.red_flags?.length) {
    y = ensureSpace(doc, y, 60)
    sectionTitle(doc, 'Catalysts & Red Flags', y)
    autoTable(doc, {
      startY: y + 8,
      head: [['Catalysts', 'Red Flags']],
      body: [[
        (report.catalysts || []).map((c) => `- ${c}`).join('\n') || '-',
        (report.red_flags || []).map((c) => `- ${c}`).join('\n') || '-',
      ]],
      theme: 'grid',
      headStyles: { fillColor: LIGHT, textColor: DARK, fontStyle: 'bold', fontSize: 9 },
      styles: { fontSize: 8.5, cellPadding: 6, valign: 'top', textColor: DARK },
      columnStyles: { 0: { cellWidth: (pageW - 2 * MARGIN) / 2 }, 1: { cellWidth: (pageW - 2 * MARGIN) / 2 } },
      margin: { left: MARGIN, right: MARGIN },
    })
    y = lastY(doc) + 20
  }

  // ── Key metrics ────────────────────────────────────────────────
  const metricRows: string[][] = []
  const keys = Object.keys(METRIC_LABELS).filter(
    (k) => analysis.metrics?.[k] !== undefined && analysis.metrics?.[k] !== null,
  )
  for (let i = 0; i < keys.length; i += 2) {
    const a = keys[i]
    const b = keys[i + 1]
    metricRows.push([
      METRIC_LABELS[a], fmt(analysis.metrics[a]),
      b ? METRIC_LABELS[b] : '', b ? fmt(analysis.metrics[b]) : '',
    ])
  }
  if (metricRows.length) {
    y = ensureSpace(doc, y, 60)
    sectionTitle(doc, 'Key Metrics', y)
    autoTable(doc, {
      startY: y + 8,
      body: metricRows,
      theme: 'striped',
      styles: { fontSize: 8.5, cellPadding: 4, textColor: DARK },
      columnStyles: {
        0: { fontStyle: 'bold', textColor: MUTED },
        2: { fontStyle: 'bold', textColor: MUTED },
      },
      margin: { left: MARGIN, right: MARGIN },
    })
    y = lastY(doc) + 20
  }

  // ── News ───────────────────────────────────────────────────────
  const newsTable = (heading: string, rows: { title: string; source: string }[]) => {
    if (!rows.length) return
    y = ensureSpace(doc, y, 60)
    sectionTitle(doc, heading, y)
    autoTable(doc, {
      startY: y + 8,
      head: [['Headline', 'Source']],
      body: rows.map((n) => [n.title, n.source]),
      theme: 'grid',
      headStyles: { fillColor: GREEN, textColor: 255, fontStyle: 'bold', fontSize: 9 },
      styles: { fontSize: 8.5, cellPadding: 5, valign: 'top', textColor: DARK },
      columnStyles: { 1: { cellWidth: 100, textColor: MUTED } },
      margin: { left: MARGIN, right: MARGIN },
    })
    y = lastY(doc) + 20
  }
  newsTable('Company News', analysis.news || [])
  const sectorLabel =
    analysis.sector && analysis.sector !== 'Unknown' ? `Industry News · ${analysis.sector}` : 'Industry News'
  newsTable(sectorLabel, analysis.industry_news || [])

  // ── Bottom line (conclusion) ───────────────────────────────────
  if (report.conclusion) {
    const c = verdictColor(report.verdict)
    const bodyLines = doc.splitTextToSize(report.conclusion, pageW - 2 * MARGIN - 24)
    const boxH = 30 + bodyLines.length * 13 + 16
    y = ensureSpace(doc, y, boxH + 20)
    sectionTitle(doc, 'Bottom Line', y)
    y += 10
    doc.setFillColor(c[0], c[1], c[2])
    // Tinted background box with a solid colored left bar
    doc.setFillColor(248, 250, 249)
    doc.roundedRect(MARGIN, y, pageW - 2 * MARGIN, boxH, 4, 4, 'F')
    doc.setFillColor(c[0], c[1], c[2])
    doc.rect(MARGIN, y, 5, boxH, 'F')
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(10.5)
    doc.setTextColor(...DARK)
    doc.text(bodyLines, MARGIN + 16, y + 22)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.5)
    doc.setTextColor(...MUTED)
    doc.text('Target horizon: up to 3 months', MARGIN + 16, y + boxH - 8)
    y += boxH + 20
  }

  addFootersAndDisclaimer(doc, report.engine)

  const fileName = `TRADELE_${analysis.symbol}_Report_${analysis.generated_at || 'report'}.pdf`
  doc.save(fileName)
}

// ── helpers ──────────────────────────────────────────────────────

function sectionTitle(doc: jsPDF, title: string, y: number): void {
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.setTextColor(...DARK)
  doc.text(title, MARGIN, y)
  doc.setDrawColor(...GREEN)
  doc.setLineWidth(1.5)
  const w = doc.getTextWidth(title)
  doc.line(MARGIN, y + 3, MARGIN + w, y + 3)
}

function ensureSpace(doc: jsPDF, y: number, needed: number): number {
  const pageH = doc.internal.pageSize.getHeight()
  if (y + needed > pageH - 50) {
    doc.addPage()
    return MARGIN + 10
  }
  return y
}

function analysisBlock(
  doc: jsPDF,
  title: string,
  rating: string | undefined,
  points: string[] | undefined,
  risks: string[] | undefined,
  y: number,
  keyLevels?: { support?: number | null; resistance?: number | null },
  industryImpact?: string,
): number {
  const pageW = doc.internal.pageSize.getWidth()
  y = ensureSpace(doc, y, 60)
  sectionTitle(doc, title, y)

  if (rating) {
    const c = verdictColor(rating)
    doc.setFillColor(...c)
    const rw = doc.getTextWidth(rating) + 16
    doc.roundedRect(MARGIN + doc.getTextWidth(title) + 12, y - 11, rw, 16, 4, 4, 'F')
    doc.setTextColor(255, 255, 255)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.5)
    doc.text(rating, MARGIN + doc.getTextWidth(title) + 20, y)
  }
  y += 16

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9.5)
  doc.setTextColor(...DARK)

  const writePoints = (items: string[], prefix: string) => {
    for (const p of items) {
      const lines = doc.splitTextToSize(`${prefix} ${p}`, pageW - 2 * MARGIN - 10)
      y = ensureSpace(doc, y, lines.length * 12 + 6)
      doc.text(lines, MARGIN + 10, y)
      y += lines.length * 12 + 2
    }
  }

  if (points?.length) writePoints(points, '-')
  if (keyLevels && (keyLevels.support != null || keyLevels.resistance != null)) {
    doc.setTextColor(...MUTED)
    doc.setFontSize(9)
    y += 2
    doc.text(
      `Support: Rs ${fmt(keyLevels.support)}    Resistance: Rs ${fmt(keyLevels.resistance)}`,
      MARGIN + 10,
      y,
    )
    y += 12
    doc.setTextColor(...DARK)
    doc.setFontSize(9.5)
  }
  if (risks?.length) {
    doc.setTextColor(...RED)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    y += 2
    doc.text('Risks:', MARGIN + 10, y)
    y += 12
    doc.setFont('helvetica', 'normal')
    writePoints(risks, '-')
    doc.setTextColor(...DARK)
  }
  if (industryImpact) {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(...MUTED)
    y += 2
    doc.text('Industry Impact:', MARGIN + 10, y)
    y += 12
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9.5)
    doc.setTextColor(...DARK)
    const lines = doc.splitTextToSize(industryImpact, pageW - 2 * MARGIN - 10)
    y = ensureSpace(doc, y, lines.length * 12 + 6)
    doc.text(lines, MARGIN + 10, y)
    y += lines.length * 12 + 2
  }
  return y + 12
}

function addFootersAndDisclaimer(doc: jsPDF, engine?: string): void {
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const total = doc.getNumberOfPages()
  const disclaimer =
    'Disclaimer: This report is generated by TRADELE AI for research and educational purposes only and does not ' +
    'constitute investment advice. Past performance and signals do not guarantee future results. Consult a SEBI-registered advisor before investing.'

  for (let i = 1; i <= total; i++) {
    doc.setPage(i)
    doc.setDrawColor(...LIGHT)
    doc.setLineWidth(1)
    doc.line(MARGIN, pageH - 42, pageW - MARGIN, pageH - 42)

    if (i === total) {
      doc.setFont('helvetica', 'italic')
      doc.setFontSize(6.8)
      doc.setTextColor(...MUTED)
      const lines = doc.splitTextToSize(disclaimer, pageW - 2 * MARGIN)
      doc.text(lines, MARGIN, pageH - 34)
    }

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...MUTED)
    doc.text(
      `© ${new Date().getFullYear()} TRADELE™  ·  AI Trading Intelligence${engine ? `  ·  engine: ${engine}` : ''}`,
      MARGIN,
      pageH - 14,
    )
    doc.text(`Page ${i} of ${total}`, pageW - MARGIN, pageH - 14, { align: 'right' })
  }
}
