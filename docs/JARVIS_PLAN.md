# JARVIS — Equity Intraday Autopilot Agent (Development Plan)

**Codename:** JARVIS  
**Scope:** Auto **Equity Intraday (MIS)** trading agent for TRADELE  
**Broker posture:** Zerodha = live market eyes · Groww = execution hands · Claude Code CLI = advisor  
**Status:** Planning — for review (no implementation yet)  
**Last updated:** 2026-09-19  
**Sibling (later):** [`FRIDAY_PLAN.md`](./FRIDAY_PLAN.md) for F&O  

> JARVIS is TRADELE’s **Equity Intraday** executor: configurable rules you set, live scans & scores, risk-gated MIS orders on Groww, and a desk UI that updates in real time. It aims to be **best-in-class operations + adaptive edge** — not a fantasy “always wins” bot.

---

## 0. Mission

Build an agent that:

1. **Scans** NSE equity with **Groww/Zerodha-style intraday filters** you configure  
2. **Scores** candidates live and ranks Long / Short  
3. **Abides by settings** — stop-loss, target, size, square-off, universe filters (e.g. avoid Large Cap)  
4. **Executes** MIS on Groww via API + **webhooks** for order/fill events  
5. **Learns** from saved outcomes (paper → approve → live) while Claude advises / vetoes  
6. Surfaces everything in a **super UI**: scores, scans, executions, live P&amp;L  

**Sequence vs FRIDAY:** Ship JARVIS first (cash/MIS is simpler). Reuse OMS / memory / webhook patterns for FRIDAY later.

---

## 1. What “world-class” means here (honest bar)

A top equity-intraday system is not one magic indicator. It is:

| Pillar | World-class bar |
|--------|------------------|
| **Universe quality** | Liquid, shortable/buyable, spread-aware, filterable like a broker terminal |
| **Regime awareness** | Don’t run breakout logic in pure chop; don’t fade strong trends blindly |
| **Risk first** | Hard SL/target/time-stop/square-off; daily loss kill; max concurrent names |
| **Execution quality** | Idempotent orders, webhook truth, reconcile vs positions |
| **Operator control** | Every rule is a setting JARVIS cannot silently ignore |
| **Feedback loop** | Every trade saved → strategy weights / filter efficacy update |
| **Auditability** | Why this stock, why this size, why vetoed — visible in UI |

**Non-claim:** No plan guarantees profit. The goal is **maximum process quality + measurable edge under your constraints**.

---

## 2. Algorithm architecture (Meta-Intraday Engine)

### 2.1 Strategy pack (equity MIS)

| ID | Playbook | When allowed | Core idea |
|----|----------|--------------|-----------|
| **J-A** | Opening drive / ORB | Trend or expansion open | Break/fail of first N-min range |
| **J-B** | Momentum continuation | Confirmed trend day | VWAP reclaim + pullback with volume |
| **J-C** | Mean reversion | **Range regime only** | Fade stretch to VWAP / prior value |
| **J-D** | Relative strength vs Nifty | Always as filter / boost | Stock vs index out/under-performance |
| **J-E** | News / catalyst overlay | Optional | Watchlist / Market Brief veto or boost |

**Meta-router:** Same philosophy as FRIDAY — pick allow-mask by **session regime** (trend / range / event), weight by **saved expectancy**, Claude can **veto or size-down** only (never invent entries without a rules signal).

### 2.2 Pipeline (one session loop)

```
Settings (locked for session unless hot-reload allowed)
    → Universe build (filters)
    → Live features (1m/5m, LTP, volume, VWAP, ATR)
    → Regime detect (index + breadth)
    → Strategy signals (J-A…J-E)
    → Score + rank
    → Claude advisor (optional veto)
    → Risk governor (SL/TP/size/limits)
    → Intent (PAPER | APPROVE | LIVE)
    → Groww MIS order
    → Webhooks / poll → fill → manage SL/TP
    → Square-off / time-stop
    → Memory save → live P&amp;L desk
```

### 2.3 Scoring (live, visible in UI)

Composite score (0–100) example weights — **all configurable**:

| Factor | Role |
|--------|------|
| Momentum / breakout quality | Structure clarity |
| Volume surge vs 20-bar avg | Participation |
| Relative strength vs Nifty | Stock vs market |
| Spread / liquidity score | Executability |
| ATR fitness (not too quiet / not chaos) | Tradeable volatility |
| Delivery / speculative flow (if available) | Intraday friendliness |
| Strategy fit to regime | Router alignment |
| Claude confidence (optional soft weight) | Narrative sanity |

UI shows **factor breakdown per symbol**, not just a black-box number.

---

## 3. Settings system (JARVIS must abide)

All settings live in a versioned **JarvisConfig** (DB + UI). Changing critical risk settings can require **re-arm** in LIVE.

### 3.1 Section — Mode & autonomy

| Setting | Type | Default (proposal) | Notes |
|---------|------|--------------------|-------|
| `mode` | enum | `OFF` | `OFF` / `SCAN_ONLY` / `PAPER` / `APPROVE` / `LIVE` |
| `claude_role` | enum | `veto_and_explain` | `off` / `explain_only` / `veto_and_explain` |
| `arm_live_required` | bool | true | Explicit arm + secret |
| `paper_slippage_bps` | int | 5–10 | Conservative paper fills |
| `hot_reload_filters` | bool | true | Filters update mid-session |
| `hot_reload_risk` | bool | false | SL/TP/daily loss need confirm in LIVE |

### 3.2 Section — Universe & broker-style filters

Inspired by **Groww / Zerodha / charting scanners** — toggles JARVIS applies **before** deep scan:

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `avoid_large_cap` | toggle | off | Exclude Nifty 50 / large-cap list |
| `large_cap_only` | toggle | off | Mutual exclusive with avoid |
| `prefer_mid_small` | toggle | on | Bias mid/small if not avoided |
| `min_price` | number | e.g. 50 | Avoid junk / extreme penny |
| `max_price` | number | e.g. 5000 | Optional ceiling |
| `min_avg_volume` | number | e.g. 5L shares | Liquidity floor |
| `min_avg_value_cr` | number | e.g. 10 | Rupee liquidity |
| `max_spread_bps` | number | e.g. 15 | Skip wide books |
| `min_atr_pct` | number | e.g. 1.0 | Need movement |
| `max_atr_pct` | number | e.g. 8.0 | Avoid chaos names |
| `exclude_gsm_asm` | toggle | on | Surveillance stocks out |
| `exclude_banned_fno_only` | n/a | — | Equity cash universe |
| `allow_short` | toggle | on | If false → Long-only MIS |
| `index_filter` | multi | Nifty500 / custom | Universe source |
| `sector_include` / `sector_exclude` | multi | empty | Sector gates |
| `watchlist_only` | toggle | off | Restrict to TRADELE watchlist |
| `max_candidates_scan` | int | 150–300 | Perf cap before score |
| `top_n_long` / `top_n_short` | int | 5 / 5 | Ranked output |
| `correlate_max` | number | 0.85 | Avoid 5 highly correlated names |

**UI pattern:** Chip toggles + numeric fields grouped as **“Scanner filters”** (broker-familiar language).

### 3.3 Section — Stop-loss & target (critical)

JARVIS never enters without a **resolved SL and target plan** (even if target is trailing-only).

#### Capture model (how levels are set)

| Mode | How SL set | How Target set |
|------|------------|----------------|
| **ATR-based** | `entry ± k_sl * ATR` | `entry ± k_tp * ATR` |
| **Structure-based** | Below swing low / above swing high (+ buffer ticks) | R-multiple or next structure |
| **Fixed %** | `sl_pct` from entry | `tp_pct` from entry |
| **Fixed ₹ risk** | Shares sized so loss ≈ `risk_rupees` at SL | Target by R-multiple |
| **Hybrid (recommended default)** | Structure SL with ATR floor/ceiling | 1.5R–2.5R or trail after 1R |

#### Settings

| Setting | Type | Default proposal | Notes |
|---------|------|------------------|-------|
| `sl_mode` | enum | `hybrid` | `atr` / `structure` / `pct` / `hybrid` |
| `tp_mode` | enum | `r_multiple` | `atr` / `pct` / `r_multiple` / `trail_only` |
| `atr_timeframe` | enum | `5m` | ATR source |
| `atr_length` | int | 14 | |
| `sl_atr_mult` | number | 1.0–1.5 | |
| `tp_atr_mult` | number | 2.0–3.0 | |
| `sl_pct` | number | 0.8 | If pct mode |
| `tp_pct` | number | 1.5 | If pct mode |
| `min_r_multiple` | number | 1.5 | Skip trade if R:R &lt; this |
| `target_r_multiple` | number | 2.0 | |
| `structure_buffer_ticks` | int | 2–5 | Beyond swing |
| `use_broker_sl_order` | toggle | on | Exchange SL-M / SL-L if Groww supports |
| `use_local_soft_sl` | toggle | on | App monitors LTP → market exit if broker SL fails |
| `trail_enabled` | toggle | on | |
| `trail_activate_r` | number | 1.0 | Start trail after 1R |
| `trail_atr_mult` | number | 0.8 | |
| `move_to_be_at_r` | number | 1.0 | Move SL to cost ± fees |
| `partial_book_at_r` | number | 1.5 | Optional scale-out % |
| `partial_book_pct` | number | 50 | |
| `max_sl_pct_hard` | number | 1.5 | Cap insane structure stops |
| `min_sl_pct_hard` | number | 0.3 | Avoid noise stops |

**UI:** Visual R:R preview on selected candidate (entry / SL / TP lines on mini chart).

### 3.4 Section — Position sizing & capital

| Setting | Type | Default | Notes |
|---------|------|---------|-------|
| `capital_rupees` | number | user set | Session capital JARVIS may use |
| `risk_per_trade_pct` | number | 0.5–1.0 | % of capital risked at SL |
| `risk_per_trade_rupees` | number | optional override | |
| `max_position_value` | number | e.g. 1L | Cap notional |
| `max_shares` | int | optional | |
| `max_concurrent_positions` | int | 2–3 | |
| `max_same_sector` | int | 1–2 | |
| `size_round_lot` | int | 1 | Equity round |

### 3.5 Section — Session timing & square-off

| Setting | Type | Default | Notes |
|---------|------|---------|-------|
| `session_start` | time | 09:20 IST | No entries before |
| `session_end_entries` | time | 14:45 IST | No new entries after |
| `force_square_off` | time | 15:15 IST | Hard flatten MIS |
| `orb_minutes` | int | 15–30 | For J-A |
| `time_stop_minutes` | int | 45–90 | Exit if thesis dead |
| `lunch_pause` | toggle | optional | 12:00–13:00 no new entries |
| `avoid_first_n_minutes` | int | 5 | Optional open chaos skip |

### 3.6 Section — Risk kill switches

| Setting | Type | Default | Notes |
|---------|------|---------|-------|
| `max_daily_loss_rupees` | number | required | → mode OFF + flatten |
| `max_daily_loss_pct` | number | e.g. 2% | |
| `max_trades_per_day` | int | e.g. 8 | Overtrading brake |
| `max_losing_streak` | int | e.g. 3 | Pause entries |
| `pause_on_feed_stale_sec` | int | 5–15 | |
| `pause_on_reconcile_fail` | toggle | on | |
| `kill_switch` | action | UI + API | Immediate flatten + block |

### 3.7 Section — Strategy enablement

| Setting | Type | Notes |
|---------|------|-------|
| `enable_j_a` … `enable_j_e` | toggles | Per-playbook |
| `router_learning` | toggle | Update weights from Memory |
| `min_score_to_trade` | number | e.g. 70 |
| `require_index_align` | toggle | Long only if Nifty not dumping hard |

### 3.8 Settings governance

- **Presets:** `Conservative` / `Balanced` / `Aggressive` (load template → editable)  
- **Versioning:** every save → `config_version`; intents store version used  
- **Abide rule:** Risk Governor rejects any intent that violates active config (logged as `BLOCKED_BY_SETTINGS`)

---

## 4. Data & webhooks

### 4.1 Market data (inbound)

| Channel | Source | Use |
|---------|--------|-----|
| REST poll | Zerodha quote / LTP / candles | Baseline live loop |
| (Phase 2) Websocket | KiteTicker | Faster triggers |
| Fallback candles | Groww historical | Gap fill |
| Account | Groww positions / orders | Truth |

### 4.2 Webhooks (core requirement)

JARVIS needs a **Webhook Gateway** so execution state is push-driven where possible.

#### Outbound (TRADELE → your listeners) — optional

| Event | Payload gist |
|-------|----------------|
| `jarvis.scan.completed` | top longs/shorts, scores |
| `jarvis.intent.created` | symbol, side, SL, TP, mode |
| `jarvis.order.submitted` | broker ids |
| `jarvis.fill` | qty, price |
| `jarvis.pnl.tick` | unrealized / realized day |
| `jarvis.kill` | reason |
| `jarvis.error` | code, message |

Secure with HMAC signature + rotateable secret.

#### Inbound (brokers / workers → TRADELE)

| Event | Purpose |
|-------|---------|
| Groww order update webhook *(if broker provides)* | Status / fills without polling only |
| Internal worker webhook | Scanner node posts results |
| Manual desk webhook | External tool can request `flatten` / `pause` with auth |

**If Groww lacks public webhooks:** implement **hybrid** — fast poll (1–2s) on open orders + emulate webhook bus internally (`JarvisEventBus`) so UI and OMS share one event model. Design API **as if** webhooks exist so broker push plugs in later with zero UI rewrite.

### 4.3 Order execution API surface (Groww)

To build (today read-only):

- Place MIS market / limit  
- Place SL / target (or local OCO emulation)  
- Modify / cancel  
- Flatten symbol / flatten all  
- Idempotency key = `intent_id`

---

## 5. Super UI — “JARVIS Desk”

Route proposal: `/jarvis` (nav: under Equity Intraday / Agents).  
Tone: **mission control** — dense but calm; live numbers primary; settings secondary drawer.

### 5.1 Layout (advanced yet intuitive)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ JARVIS   [MODE● PAPER]  Feed●  Claude●  Kill Switch     Day P&amp;L +₹12,400 │
├─────────────┬────────────────────────────────────────────┬───────────────┤
│ SETTINGS    │  LIVE BOARD                                │  POSITIONS    │
│ sections    │  heat list Long/Short scores               │  + orders     │
│ (drawer)    │  sparkline · R:R · regime badge            │  live uPNL    │
├─────────────┴────────────────────────────────────────────┴───────────────┤
│ TIMELINE: scans → intents → fills → exits → learning notes               │
└──────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Must-have live widgets

1. **Hero day P&amp;L** — realized + unrealized, green/red, updates on fill/webhook  
2. **Mode & arm** — impossible to miss LIVE vs PAPER  
3. **Kill switch** — always visible  
4. **Scanner table** — symbol, score, factors, strategy tag, SL/TP preview, 1-click Approve  
5. **Execution tape** — order states streaming  
6. **Open positions** — entry, SL, TP, MTM, trail state  
7. **Regime chip** — TREND / RANGE / EVENT  
8. **Settings drawer** — sections from §3 with search  
9. **Health** — Zerodha age, Groww age, webhook lag  
10. **Explain drawer** — Claude + rules reasons for selected symbol  

### 5.3 UX principles

- One glance = “am I safe and making/losing money?”  
- Scores animate on refresh; no full-page reloads (SSE/websocket to UI)  
- Dangerous actions (Arm LIVE, Kill) use confirm + optional PIN  
- Mobile: P&amp;L + Kill + positions first; settings secondary  

### 5.4 Reuse from TRADELE today

- Equity Intraday momentum scan / conviction chart patterns  
- MyTrade Equity Intraday calendar for post-trade review  
- Existing `claude_cli` LLM path for advisor  

---

## 6. Learning & memory

Save per intent/trade:

- Config version, filters snapshot, features, score breakdown  
- Strategy id, regime, Claude verdict  
- Entry/SL/TP plan vs actual fills  
- MAE / MFE / P&amp;L / hold time  
- Exit reason (target, SL, trail, time, square-off, kill, reject)

Nightly / EOD:

- Strategy scorecards by regime  
- Filter efficacy (“avoid large cap” on/off performance)  
- Propose setting tweaks (Claude weekly brief) — **human apply**

---

## 7. Phased delivery

### Phase 0 — Go / no-go (few days)

- Confirm Groww MIS **place/cancel** API  
- Confirm Zerodha equity live quotes for universe size  
- Lock capital + max daily loss  
- Decide Claude role day-one  

### Phase 1 — Desk + settings + scan (no orders)

- JarvisConfig UI (all §3 sections)  
- Filter pipeline + live scores  
- SCAN_ONLY / PAPER intents with SL/TP resolved on chart  
- Event bus → UI live updates (mock fills in paper)  

### Phase 2 — Risk + paper fidelity

- Meta-router J-A/B/C  
- Soft SL/TP manager on LTP  
- Memory + day P&amp;L engine  
- Webhook outbound to optional URL  

### Phase 3 — Groww execution

- OMS + idempotent intents  
- APPROVE mode → 1-share / tiny size LIVE  
- Inbound order status (poll and/or webhook)  
- Reconcile vs Groww positions  
- Force square-off job  

### Phase 4 — Polish to “super”

- SSE/WS UI, animations, presets  
- Learning weights, streak brakes  
- Correlation / sector caps  
- Audit export  

### Phase 5 — Hand-off patterns to FRIDAY

- Shared OMS / webhook / kill / memory abstractions  

---

## 8. Proposed module map (for later implementation)

```
TRADELE/services/jarvis/
  config.py          # settings schema + presets + abide checks
  universe.py        # broker-style filters
  features.py
  regime.py
  strategies/        # j_a … j_e
  scorer.py
  router.py
  advisor_claude.py
  risk.py            # SL/TP resolve + sizing + kills
  oms.py
  webhooks.py        # in/out + HMAC
  events.py          # internal bus
  paper.py
  memory.py
  squareoff.py

TRADELE/api/routes/jarvis.py
UI/src/pages/JarvisDesk.tsx
UI/src/components/jarvis/*   # SettingsPanel, LiveBoard, Tape, Positions
docs/JARVIS_PLAN.md          # this file
```

---

## 9. Success criteria (review gates)

| Gate | Pass when |
|------|-----------|
| Settings fidelity | Zero LIVE intents violate SL/TP/universe rules |
| Paper edge | Expectancy &gt; 0 after slippage assumption over sample weeks |
| Ops | Square-off never misses; reconcile errors = 0 before size-up |
| UI | Operator can arm, kill, and read day P&amp;L in &lt; 2 seconds glance |
| Webhooks/events | UI and OMS stay consistent under burst fills |
| Learning | Bad regime×strategy pairs get demoted automatically |

---

## 10. Risks & explicit non-goals

**Risks:** API gaps, stale feeds, gap through SL, overtrading, overfitting filters, Claude latency.

**Non-goals (V1):** HFT, F&amp;O inside JARVIS, overnight CNC, naked “Claude decided buy,” multi-broker dual execution.

---

## 11. Review checklist (please mark)

1. Confirm **JARVIS before FRIDAY**?  
2. Day-one mode path: `SCAN_ONLY` → `PAPER` → `APPROVE` → `LIVE` OK?  
3. Default SL/TP: **hybrid + R-multiple** OK, or prefer fixed %?  
4. `avoid_large_cap` default on or off?  
5. Shorts enabled day-one?  
6. Claude: `explain_only` or `veto_and_explain`?  
7. Webhooks: outbound to your URL required day-one, or internal bus first?  
8. Max daily loss + capital numbers for first LIVE?  
9. Nav home: `/jarvis` or embed inside Equity Intraday page?  

---

## 12. After your review

Once checklist answers are in:

1. Lock config schema (§3) as source of truth  
2. Spike Groww MIS place-order + event model  
3. Build Phase 1 desk (settings + live scores) with **no LIVE arm path enabled by default**

---

*End of JARVIS plan — awaiting your review.*
