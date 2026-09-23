import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import type { HorizonOutlook, IntradayCandidate, StockAnalysis, TomorrowMomentumScan } from '../api/client'

const GREEN: [number, number, number] = [0, 179, 134]
const GREEN_DARK: [number, number, number] = [0, 160, 120]
const DARK: [number, number, number] = [25, 28, 31]
const MUTED: [number, number, number] = [124, 126, 140]
const RED: [number, number, number] = [235, 91, 60]
const LIGHT: [number, number, number] = [245, 247, 246]

const MARGIN = 44
const FOOTER_H = 48
const LINE_H = 13

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

/** Strip unicode jsPDF Helvetica cannot render cleanly (prevents spaced-letter glitches). */
function pdfSafe(raw: unknown): string {
  if (raw === null || raw === undefined) return ''
  return String(raw)
    .replace(/\u20B9/g, 'Rs ')
    .replace(/₹/g, 'Rs ')
    .replace(/[\u2018\u2019\u2032]/g, "'")
    .replace(/[\u201C\u201D\u2033]/g, '"')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/\u00A0/g, ' ')
    .replace(/[^\x09\x0A\x0D\x20-\x7E]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  const n = Number(v)
  if (Number.isNaN(n)) return pdfSafe(v)
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function verdictColor(v?: string): [number, number, number] {
  const b = pdfSafe(v).toLowerCase()
  if (b.includes('buy') || b.includes('accumulate') || b.includes('bull') || b.includes('positive') || b.includes('strong'))
    return GREEN
  if (b.includes('avoid') || b.includes('reduce') || b.includes('sell') || b.includes('bear') || b.includes('negative') || b.includes('weak'))
    return RED
  return MUTED
}

function contentWidth(doc: jsPDF): number {
  return doc.internal.pageSize.getWidth() - 2 * MARGIN
}

function lastY(doc: jsPDF): number {
  const d = doc as unknown as { lastAutoTable?: { finalY: number } }
  return d.lastAutoTable?.finalY ?? MARGIN
}

function wrapText(doc: jsPDF, text: string, maxW: number): string[] {
  return doc.splitTextToSize(pdfSafe(text), maxW) as string[]
}

export function exportStockReportPdf(analysis: StockAnalysis): void {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const cw = contentWidth(doc)
  const report = analysis.report || {}

  // ── Brand header band ──────────────────────────────────────────
  doc.setFillColor(...GREEN)
  doc.rect(0, 0, pageW, 70, 'F')
  doc.setFillColor(255, 255, 255)
  doc.roundedRect(MARGIN, 22, 26, 26, 6, 6, 'F')
  doc.setTextColor(...GREEN_DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.text('T', MARGIN + 13, 40, { align: 'center' })
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(20)
  doc.text('TRADELE', MARGIN + 38, 38)
  doc.setFontSize(8)
  doc.text('TM', MARGIN + 38 + doc.getTextWidth('TRADELE') + 3, 30)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text('AI Trading Intelligence', MARGIN + 38, 52)
  doc.setFontSize(9)
  doc.text('Equity Research Report', pageW - MARGIN, 34, { align: 'right' })
  doc.text(`Generated: ${pdfSafe(analysis.generated_at)}`, pageW - MARGIN, 48, { align: 'right' })

  let y = 96

  // ── Title row ──────────────────────────────────────────────────
  doc.setTextColor(...DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(18)
  const companyName = pdfSafe(analysis.company || analysis.symbol)
  doc.text(companyName, MARGIN, y)

  const vColor = verdictColor(report.verdict)
  const pillW = 140
  const pillX = pageW - MARGIN - pillW
  doc.setFillColor(...vColor)
  doc.roundedRect(pillX, y - 20, pillW, 44, 6, 6, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(14)
  doc.setFont('helvetica', 'bold')
  doc.text(pdfSafe(report.verdict || 'HOLD').toUpperCase(), pillX + pillW / 2, y - 2, { align: 'center' })
  if (typeof report.conviction === 'number') {
    doc.setFontSize(8)
    doc.setFont('helvetica', 'normal')
    doc.text(`${report.conviction}% conviction`, pillX + pillW / 2, y + 14, { align: 'center' })
  }

  y += 20
  doc.setTextColor(...MUTED)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  const subParts = [
    pdfSafe(analysis.symbol),
    analysis.sector && analysis.sector !== 'Unknown' ? pdfSafe(analysis.sector) : null,
  ].filter(Boolean)
  doc.text(subParts.join('  |  '), MARGIN, y)

  y += 14
  doc.setTextColor(...DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  const chg = Number(analysis.metrics?.change_pct)
  const priceStr = `Rs ${fmt(analysis.metrics?.close)} (${chg >= 0 ? '+' : ''}${fmt(analysis.metrics?.change_pct)}%)`
  doc.text(priceStr, MARGIN, y)

  y += 22

  // ── Executive summary ──────────────────────────────────────────
  if (report.summary) {
    y = ensureSpace(doc, y, 40)
    sectionTitle(doc, 'Executive Summary', y)
    y += 16
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(10)
    doc.setTextColor(...DARK)
    const lines = wrapText(doc, report.summary, cw - 8)
    y = writeLines(doc, lines, MARGIN, y)
    y += 12
  }

  // ── Outlook ────────────────────────────────────────────────────
  const o = report.outlook || {}
  const outlookRow = (label: string, h?: HorizonOutlook) => [
    label,
    pdfSafe(h?.bias || '-'),
    pdfSafe(h?.expected_range || '-'),
    typeof h?.confidence === 'number' ? `${h.confidence}%` : '-',
    pdfSafe(h?.rationale || '-'),
  ]
  y = ensureSpace(doc, y, 80)
  sectionTitle(doc, 'Outlook', y)
  autoTable(doc, {
    startY: y + 10,
    head: [['Horizon', 'Bias', 'Expected Range', 'Conf.', 'Rationale']],
    body: [
      outlookRow('Next Week', o.next_week),
      outlookRow('Next Month', o.next_month),
      outlookRow('Next 3 Months', o.next_3_months),
    ],
    theme: 'grid',
    headStyles: { fillColor: GREEN, textColor: 255, fontStyle: 'bold', fontSize: 9, font: 'helvetica' },
    styles: {
      font: 'helvetica',
      fontSize: 8.5,
      cellPadding: 5,
      textColor: DARK,
      valign: 'top',
      overflow: 'linebreak',
      cellWidth: 'wrap',
    },
    columnStyles: {
      0: { fontStyle: 'bold', cellWidth: 62 },
      1: { cellWidth: 48, halign: 'center' },
      2: { cellWidth: 82 },
      3: { cellWidth: 32, halign: 'center' },
      4: { cellWidth: cw - 62 - 48 - 82 - 32 },
    },
    margin: { left: MARGIN, right: MARGIN },
    tableWidth: cw,
    didParseCell: (data) => {
      if (data.section === 'body' && data.column.index === 1) {
        data.cell.styles.textColor = verdictColor(String(data.cell.raw))
        data.cell.styles.fontStyle = 'bold'
      }
    },
  })
  y = lastY(doc) + 22

  // ── Trade plan ─────────────────────────────────────────────────
  const e = report.entry
  if (e) {
    y = ensureSpace(doc, y, 60)
    sectionTitle(doc, 'Trade Plan', y)
    autoTable(doc, {
      startY: y + 10,
      head: [['Buy Zone', 'Stop Loss', 'Target 1', 'Target 2', 'Risk / Reward']],
      body: [[
        pdfSafe(e.buy_zone || '-'),
        e.stop_loss != null ? `Rs ${fmt(e.stop_loss)}` : '-',
        e.target_1 != null ? `Rs ${fmt(e.target_1)}` : '-',
        e.target_2 != null ? `Rs ${fmt(e.target_2)}` : '-',
        pdfSafe(e.risk_reward || '-'),
      ]],
      theme: 'grid',
      headStyles: { fillColor: DARK, textColor: 255, fontStyle: 'bold', fontSize: 9, font: 'helvetica' },
      styles: { font: 'helvetica', fontSize: 9, cellPadding: 6, halign: 'center', textColor: DARK, overflow: 'linebreak' },
      margin: { left: MARGIN, right: MARGIN },
      tableWidth: cw,
    })
    y = lastY(doc) + 22
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
      startY: y + 10,
      head: [['Catalysts', 'Red Flags']],
      body: [[
        (report.catalysts || []).map((c) => `- ${pdfSafe(c)}`).join('\n') || '-',
        (report.red_flags || []).map((c) => `- ${pdfSafe(c)}`).join('\n') || '-',
      ]],
      theme: 'grid',
      headStyles: { fillColor: LIGHT, textColor: DARK, fontStyle: 'bold', fontSize: 9, font: 'helvetica' },
      styles: { font: 'helvetica', fontSize: 8.5, cellPadding: 6, valign: 'top', textColor: DARK, overflow: 'linebreak' },
      columnStyles: { 0: { cellWidth: cw / 2 }, 1: { cellWidth: cw / 2 } },
      margin: { left: MARGIN, right: MARGIN },
      tableWidth: cw,
    })
    y = lastY(doc) + 22
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
      startY: y + 10,
      body: metricRows,
      theme: 'striped',
      styles: { font: 'helvetica', fontSize: 8.5, cellPadding: 4, textColor: DARK, overflow: 'linebreak' },
      columnStyles: {
        0: { fontStyle: 'bold', textColor: MUTED, cellWidth: cw * 0.28 },
        1: { cellWidth: cw * 0.22 },
        2: { fontStyle: 'bold', textColor: MUTED, cellWidth: cw * 0.28 },
        3: { cellWidth: cw * 0.22 },
      },
      margin: { left: MARGIN, right: MARGIN },
      tableWidth: cw,
    })
    y = lastY(doc) + 22
  }

  // ── News ───────────────────────────────────────────────────────
  const newsTable = (heading: string, rows: { title: string; source: string }[]) => {
    if (!rows.length) return
    y = ensureSpace(doc, y, 60)
    sectionTitle(doc, heading, y)
    autoTable(doc, {
      startY: y + 10,
      head: [['Headline', 'Source']],
      body: rows.map((n) => [pdfSafe(n.title), pdfSafe(n.source)]),
      theme: 'grid',
      headStyles: { fillColor: GREEN, textColor: 255, fontStyle: 'bold', fontSize: 9, font: 'helvetica' },
      styles: { font: 'helvetica', fontSize: 8.5, cellPadding: 5, valign: 'top', textColor: DARK, overflow: 'linebreak' },
      columnStyles: { 0: { cellWidth: cw - 100 }, 1: { cellWidth: 100, textColor: MUTED } },
      margin: { left: MARGIN, right: MARGIN },
      tableWidth: cw,
    })
    y = lastY(doc) + 22
  }
  newsTable('Company News', analysis.news || [])
  const sectorLabel =
    analysis.sector && analysis.sector !== 'Unknown' ? `Industry News - ${pdfSafe(analysis.sector)}` : 'Industry News'
  newsTable(sectorLabel, analysis.industry_news || [])

  // ── Bottom line ────────────────────────────────────────────────
  if (report.conclusion) {
    const c = verdictColor(report.verdict)
    const textW = cw - 28
    const bodyLines = wrapText(doc, report.conclusion, textW)
    const boxH = 36 + bodyLines.length * LINE_H
    y = ensureSpace(doc, y, boxH + 24)
    sectionTitle(doc, 'Bottom Line', y)
    y += 14
    doc.setFillColor(248, 250, 249)
    doc.roundedRect(MARGIN, y, cw, boxH, 4, 4, 'F')
    doc.setFillColor(c[0], c[1], c[2])
    doc.rect(MARGIN, y, 5, boxH, 'F')
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(10)
    doc.setTextColor(...DARK)
    writeLines(doc, bodyLines, MARGIN + 14, y + 20)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    doc.setTextColor(...MUTED)
    doc.text('Target horizon: up to 3 months', MARGIN + 14, y + boxH - 10)
    y += boxH + 20
  }

  addFootersAndDisclaimer(doc)

  const fileName = `TRADELE_${analysis.symbol}_Report_${analysis.generated_at || 'report'}.pdf`
  doc.save(fileName)
}

function sectionTitle(doc: jsPDF, title: string, y: number): void {
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.setTextColor(...DARK)
  doc.text(pdfSafe(title), MARGIN, y)
  doc.setDrawColor(...GREEN)
  doc.setLineWidth(1.5)
  const w = doc.getTextWidth(pdfSafe(title))
  doc.line(MARGIN, y + 3, MARGIN + w, y + 3)
}

function ensureSpace(doc: jsPDF, y: number, needed: number): number {
  const pageH = doc.internal.pageSize.getHeight()
  if (y + needed > pageH - FOOTER_H) {
    doc.addPage()
    return MARGIN + 10
  }
  return y
}

function writeLines(doc: jsPDF, lines: string[], x: number, y: number): number {
  for (const line of lines) {
    y = ensureSpace(doc, y, LINE_H + 2)
    doc.text(line, x, y)
    y += LINE_H
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
  const cw = contentWidth(doc)
  y = ensureSpace(doc, y, 50)
  sectionTitle(doc, title, y)
  y += 16

  if (rating) {
    const safeRating = pdfSafe(rating)
    const c = verdictColor(safeRating)
    doc.setFillColor(...c)
    const rw = Math.min(doc.getTextWidth(safeRating) + 18, cw * 0.45)
    doc.roundedRect(MARGIN, y - 2, rw, 18, 4, 4, 'F')
    doc.setTextColor(255, 255, 255)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.5)
    doc.text(safeRating, MARGIN + 9, y + 10)
    y += 24
  }

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9.5)
  doc.setTextColor(...DARK)

  const writePoints = (items: string[], prefix: string) => {
    for (const p of items) {
      const lines = wrapText(doc, `${prefix} ${p}`, cw - 16)
      y = writeLines(doc, lines, MARGIN + 8, y)
      y += 2
    }
  }

  if (points?.length) writePoints(points.map(pdfSafe), '-')
  if (keyLevels && (keyLevels.support != null || keyLevels.resistance != null)) {
    doc.setTextColor(...MUTED)
    doc.setFontSize(9)
    y += 4
    y = ensureSpace(doc, y, LINE_H)
    doc.text(
      `Support: Rs ${fmt(keyLevels.support)}    Resistance: Rs ${fmt(keyLevels.resistance)}`,
      MARGIN + 8,
      y,
    )
    y += LINE_H + 2
    doc.setTextColor(...DARK)
    doc.setFontSize(9.5)
  }
  if (risks?.length) {
    doc.setTextColor(...RED)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    y += 4
    y = ensureSpace(doc, y, LINE_H)
    doc.text('Risks:', MARGIN + 8, y)
    y += LINE_H + 2
    doc.setFont('helvetica', 'normal')
    writePoints(risks.map(pdfSafe), '-')
    doc.setTextColor(...DARK)
  }
  if (industryImpact) {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(...MUTED)
    y += 4
    y = ensureSpace(doc, y, LINE_H)
    doc.text('Industry Impact:', MARGIN + 8, y)
    y += LINE_H + 2
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9.5)
    doc.setTextColor(...DARK)
    const lines = wrapText(doc, industryImpact, cw - 16)
    y = writeLines(doc, lines, MARGIN + 8, y)
    y += 2
  }
  return y + 10
}

function addFootersAndDisclaimer(doc: jsPDF): void {
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()
  const total = doc.getNumberOfPages()
  const cw = contentWidth(doc)
  const disclaimer =
    'Disclaimer: This report is generated by TRADELE AI for research and educational purposes only and does not ' +
    'constitute investment advice. Past performance and signals do not guarantee future results. Consult a SEBI-registered advisor before investing.'

  for (let i = 1; i <= total; i++) {
    doc.setPage(i)
    doc.setDrawColor(...LIGHT)
    doc.setLineWidth(1)
    doc.line(MARGIN, pageH - FOOTER_H + 4, pageW - MARGIN, pageH - FOOTER_H + 4)

    if (i === total) {
      doc.setFont('helvetica', 'italic')
      doc.setFontSize(6.8)
      doc.setTextColor(...MUTED)
      const lines = wrapText(doc, disclaimer, cw)
      doc.text(lines, MARGIN, pageH - FOOTER_H + 14)
    }

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...MUTED)
    doc.text(
      `(c) ${new Date().getFullYear()} TRADELE - AI Trading Intelligence`,
      MARGIN,
      pageH - 16,
    )
    doc.text(`Page ${i} of ${total}`, pageW - MARGIN, pageH - 16, { align: 'right' })
  }
}

/* ── Intraday tomorrow momentum report ───────────────────────────── */

function sortByScore(list: IntradayCandidate[]): IntradayCandidate[] {
  return [...list].sort((a, b) => {
    const c = (b.conviction || 0) - (a.conviction || 0)
    if (c !== 0) return c
    return (Number(b.score) || 0) - (Number(a.score) || 0)
  })
}

function writeCandidateSection(
  doc: jsPDF,
  title: string,
  accent: [number, number, number],
  items: IntradayCandidate[],
  y: number,
): number {
  const pageH = doc.internal.pageSize.getHeight()
  const cw = contentWidth(doc)
  const bottom = pageH - FOOTER_H - 24

  const ensure = (need: number) => {
    if (y + need > bottom) {
      doc.addPage()
      y = MARGIN
    }
  }

  ensure(28)
  doc.setFillColor(...accent)
  doc.roundedRect(MARGIN, y - 12, cw, 22, 4, 4, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.text(title, MARGIN + 10, y + 2)
  y += 24

  if (!items.length) {
    doc.setTextColor(...MUTED)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(10)
    doc.text('No candidates.', MARGIN, y)
    return y + 18
  }

  items.forEach((c, idx) => {
    ensure(120)
    doc.setTextColor(...DARK)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(13)
    doc.text(`#${idx + 1}  ${pdfSafe(c.symbol)}`, MARGIN, y)
    doc.setTextColor(...accent)
    doc.text(`${c.conviction ?? 0}% conviction`, pageWRight(doc), y, { align: 'right' })
    y += LINE_H + 2

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.setTextColor(...MUTED)
    doc.text(
      pdfSafe(
        `${c.can_trade_tomorrow ? 'Ready tomorrow' : 'Needs confirmation'}  |  ${c.checks_passed}/${c.checks_total} checks  |  score ${c.score ?? '-'}  |  bars: ${c.data_source || '-'}`,
      ),
      MARGIN,
      y,
    )
    y += LINE_H

    doc.setTextColor(...DARK)
    doc.setFontSize(9.5)
    const verdictLines = wrapText(doc, c.verdict || '', cw)
    verdictLines.forEach((ln) => {
      ensure(LINE_H)
      doc.text(ln, MARGIN, y)
      y += LINE_H
    })

    if (c.narrative) {
      doc.setTextColor(...MUTED)
      wrapText(doc, c.narrative, cw).forEach((ln) => {
        ensure(LINE_H)
        doc.text(ln, MARGIN, y)
        y += LINE_H
      })
    }
    if (c.plan) {
      doc.setFont('helvetica', 'italic')
      wrapText(doc, c.plan, cw).forEach((ln) => {
        ensure(LINE_H)
        doc.text(ln, MARGIN, y)
        y += LINE_H
      })
      doc.setFont('helvetica', 'normal')
    }

    const m = c.metrics || {}
    autoTable(doc, {
      startY: y + 4,
      margin: { left: MARGIN, right: MARGIN },
      head: [['Close', 'VWAP', 'EMA9', 'EMA20', 'RCI', 'Vol x', 'Day %']],
      body: [[
        fmt(m.close),
        fmt(m.vwap),
        fmt(m.ema_9),
        fmt(m.ema_20),
        fmt(m.rci),
        fmt(m.volume_ratio),
        fmt(m.day_return_pct),
      ]],
      theme: 'grid',
      headStyles: { fillColor: LIGHT, textColor: MUTED, fontSize: 8, fontStyle: 'bold' },
      bodyStyles: { textColor: DARK, fontSize: 9 },
      styles: { cellPadding: 4 },
    })
    y = lastY(doc) + 8

    const checks = (c.checks || []).map((ch) => [
      ch.passed ? 'PASS' : 'FAIL',
      pdfSafe(ch.label),
      pdfSafe(ch.detail),
    ])
    if (checks.length) {
      ensure(40)
      autoTable(doc, {
        startY: y,
        margin: { left: MARGIN, right: MARGIN },
        head: [['', 'Check', 'Detail']],
        body: checks,
        theme: 'plain',
        headStyles: { fillColor: LIGHT, textColor: MUTED, fontSize: 8 },
        bodyStyles: { textColor: DARK, fontSize: 8 },
        columnStyles: { 0: { cellWidth: 36 }, 1: { cellWidth: 160 } },
        didParseCell: (data) => {
          if (data.section === 'body' && data.column.index === 0) {
            const v = String(data.cell.raw || '')
            data.cell.styles.textColor = v === 'PASS' ? GREEN : RED
            data.cell.styles.fontStyle = 'bold'
          }
        },
      })
      y = lastY(doc) + 14
    } else {
      y += 10
    }
  })

  return y
}

function pageWRight(doc: jsPDF): number {
  return doc.internal.pageSize.getWidth() - MARGIN
}

export function exportIntradayMomentumPdf(scan: TomorrowMomentumScan): void {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const cw = contentWidth(doc)
  const longs = sortByScore(scan.longs || [])
  const shorts = sortByScore(scan.shorts || [])

  doc.setFillColor(...GREEN)
  doc.rect(0, 0, pageW, 70, 'F')
  doc.setFillColor(255, 255, 255)
  doc.roundedRect(MARGIN, 22, 26, 26, 6, 6, 'F')
  doc.setTextColor(...GREEN_DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.text('T', MARGIN + 13, 40, { align: 'center' })
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(20)
  doc.text('TRADELE', MARGIN + 38, 38)
  doc.setFontSize(8)
  doc.text('TM', MARGIN + 38 + doc.getTextWidth('TRADELE') + 3, 30)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text('AI Trading Intelligence', MARGIN + 38, 52)
  doc.setFontSize(9)
  doc.text('Tomorrow Intraday Momentum', pageW - MARGIN, 34, { align: 'right' })
  doc.text(`As of: ${pdfSafe(scan.as_of || '-')}`, pageW - MARGIN, 48, { align: 'right' })

  let y = 96
  doc.setTextColor(...DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.text('Late-session momentum report', MARGIN, y)
  y += 18
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(...MUTED)
  const meta = [
    `Run #${scan.run_id ?? '-'}`,
    `Prefill ${scan.prefiltered ?? 0}`,
    `Scanned ${scan.scanned ?? 0}`,
    `Sources: ${(scan.sources || []).join(', ') || '-'}`,
    scan.rate_limited ? 'Rate-limited mid-run' : null,
  ]
    .filter(Boolean)
    .join('  |  ')
  wrapText(doc, meta, cw).forEach((ln) => {
    doc.text(ln, MARGIN, y)
    y += LINE_H
  })
  if (scan.pattern) {
    wrapText(doc, scan.pattern, cw).forEach((ln) => {
      doc.text(ln, MARGIN, y)
      y += LINE_H
    })
  }
  y += 10

  // Summary table
  autoTable(doc, {
    startY: y,
    margin: { left: MARGIN, right: MARGIN },
    head: [['#', 'Side', 'Symbol', 'Conviction', 'Checks', 'Ready', 'Day %']],
    body: [
      ...longs.map((c, i) => [
        String(i + 1),
        'LONG',
        pdfSafe(c.symbol),
        `${c.conviction}%`,
        `${c.checks_passed}/${c.checks_total}`,
        c.can_trade_tomorrow ? 'Yes' : 'No',
        fmt(c.metrics?.day_return_pct),
      ]),
      ...shorts.map((c, i) => [
        String(i + 1),
        'SHORT',
        pdfSafe(c.symbol),
        `${c.conviction}%`,
        `${c.checks_passed}/${c.checks_total}`,
        c.can_trade_tomorrow ? 'Yes' : 'No',
        fmt(c.metrics?.day_return_pct),
      ]),
    ],
    theme: 'grid',
    headStyles: { fillColor: GREEN, textColor: [255, 255, 255], fontSize: 9 },
    bodyStyles: { textColor: DARK, fontSize: 9 },
    didParseCell: (data) => {
      if (data.section === 'body' && data.column.index === 1) {
        const v = String(data.cell.raw || '')
        data.cell.styles.textColor = v === 'LONG' ? GREEN : RED
        data.cell.styles.fontStyle = 'bold'
      }
    },
  })
  y = lastY(doc) + 18

  y = writeCandidateSection(doc, 'TOP 3 LONG (by conviction score)', GREEN, longs, y)
  y = writeCandidateSection(doc, 'TOP 3 SHORT (by conviction score)', RED, shorts, y)

  addFootersAndDisclaimer(doc)
  const stamp = (scan.as_of || new Date().toISOString().slice(0, 10)).replace(/-/g, '')
  doc.save(`TRADELE_Intraday_Momentum_${stamp}.pdf`)
}

type WatchlistPdfTurn = {
  role: 'user' | 'analyst'
  text: string
  answer?: {
    summary_plain?: string
    summary_technical?: string
    verdict?: string
    conviction?: number
    catalysts?: string[]
    risks?: string[]
    citations?: { source: string; detail: string }[]
    blocked?: boolean
  }
  sources?: string[]
}

export function exportWatchlistChatPdf(
  symbol: string,
  company: string,
  turns: WatchlistPdfTurn[],
): void {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const cw = contentWidth(doc)

  doc.setFillColor(...GREEN)
  doc.rect(0, 0, pageW, 70, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(20)
  doc.text('TRADELE Watchlist Analyst', MARGIN, 42)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text(`${pdfSafe(symbol)} — ${pdfSafe(company)}`, pageW - MARGIN, 42, { align: 'right' })

  let y = 96
  doc.setTextColor(...DARK)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  doc.text('Analyst chat transcript', MARGIN, y)
  y += 20

  for (const t of turns) {
    if (y > doc.internal.pageSize.getHeight() - FOOTER_H - 40) {
      doc.addPage()
      y = MARGIN
    }
    if (t.role === 'user') {
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(10)
      doc.setTextColor(...MUTED)
      doc.text('You', MARGIN, y)
      y += LINE_H
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(...DARK)
      wrapText(doc, pdfSafe(t.text), cw).forEach((ln) => {
        doc.text(ln, MARGIN, y)
        y += LINE_H
      })
      y += 8
      continue
    }
    const ans = t.answer
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(10)
    doc.setTextColor(...verdictColor(ans?.verdict))
    const head = ans?.blocked
      ? 'Blocked'
      : `${pdfSafe(ans?.verdict || 'neutral').toUpperCase()}${typeof ans?.conviction === 'number' ? ` · ${ans.conviction}%` : ''}`
    doc.text('Analyst', MARGIN, y)
    doc.text(head, pageW - MARGIN, y, { align: 'right' })
    y += LINE_H
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(...DARK)
    const body = pdfSafe(ans?.summary_plain || t.text)
    wrapText(doc, body, cw).forEach((ln) => {
      doc.text(ln, MARGIN, y)
      y += LINE_H
    })
    if (ans?.summary_technical) {
      y += 4
      doc.setFontSize(9)
      doc.setTextColor(...MUTED)
      wrapText(doc, pdfSafe(ans.summary_technical), cw).forEach((ln) => {
        doc.text(ln, MARGIN, y)
        y += LINE_H - 2
      })
      doc.setFontSize(10)
      doc.setTextColor(...DARK)
    }
    if (ans?.risks?.length) {
      y += 6
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(9)
      doc.text('Risks', MARGIN, y)
      y += LINE_H
      doc.setFont('helvetica', 'normal')
      for (const r of ans.risks.slice(0, 5)) {
        wrapText(doc, `- ${pdfSafe(r)}`, cw).forEach((ln) => {
          doc.text(ln, MARGIN + 8, y)
          y += LINE_H - 2
        })
      }
    }
    y += 14
  }

  addFootersAndDisclaimer(doc)
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  doc.save(`TRADELE_Watchlist_${pdfSafe(symbol)}_${stamp}.pdf`)
}
