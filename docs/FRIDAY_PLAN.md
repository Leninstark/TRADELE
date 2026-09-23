# FRIDAY — Adaptive F&O Autopilot Development Plan

**Codename:** FRIDAY (Tony Stark’s executor — TRADELE’s live F&O brain + hands)  
**Status:** Planning — for review (no live execution yet)  
**Owner:** TRADELE / MyTrade  
**Last updated:** 2026-09-18  
**Supersedes:** [`STRIKE_PLAN.md`](./STRIKE_PLAN.md) (renamed product)

> FRIDAY does not “promise profits.” It is a **risk-gated, learn-and-adapt** system that uses **live broker data**, **rules engines**, and **Claude Code CLI** for reasoning — then executes **only on Groww** after hard safety gates.

---

## 0. Product one-liner

**FRIDAY** watches live F&O markets (Zerodha + Groww), picks the **best active strategy for the current regime**, improves from **saved outcomes**, and can place / manage Groww F&O orders on your behalf — starting in paper, then approve-each, then armed LIVE.

Tagline options:

- *“FRIDAY online — eyes on Zerodha, hands on Groww.”*
- *“Always learning. Never unsupervised without a kill switch.”*

---

## 1. Design thesis (what “best” means here)

The winning system is **not** one fixed algo forever.

It is a **strategy portfolio + meta-controller** that can:

| Capability | Meaning |
|------------|---------|
| **Switch strategy** | When market regime changes (trend → chop → event), FRIDAY demotes losing playbooks and promotes fit ones |
| **Learn from data** | Every paper/live trade is saved; weights, filters, and veto rules update from outcomes |
| **Stay human-safe** | Risk, mode, and kill switch always override “smart” suggestions |
| **Use Claude behind the screen** | Claude Code CLI (`LLM_PROVIDER=claude_cli`) reasons over structured live snapshots — it does **not** invent lot sizes or bypass OMS |

**Core idea:** *Rules trade. Claude advises & explains. Memory decides what to trust next.*

---

## 2. Top 5 algo families (candidates)

These are the five strongest, battle-tested **F&O-suitable** families for Indian index/stock derivatives — ranked for TRADELE’s stack (Zerodha data, Groww execution, Claude assist).

### Plan A — Opening Range Breakout + Failed Breakout (ORB / IBF)

| | |
|--|--|
| **What** | Trade break of first 15–30 min range on Nifty / BankNifty futures (or ATM options later) |
| **Edge** | Session liquidity + clear invalidation |
| **Needs** | Minute candles, session clock IST, ATR stops |
| **Fails when** | Chop / fakeouts around RBI / event opens |
| **Learnable knobs** | Range minutes, buffer ticks, time-stop, which weekdays work |

### Plan B — Trend / Momentum Continuation (VWAP + structure)

| | |
|--|--|
| **What** | After trend day confirms (higher highs / VWAP reclaim), trade pullbacks with trend |
| **Edge** | Captures the meat of directional F&O days |
| **Needs** | 5m candles, VWAP, swing structure |
| **Fails when** | Mean-revert days, lunch chop |
| **Learnable knobs** | Pullback depth, ADX/ATR filters, max holds |

### Plan C — Mean Reversion at extremes (Bollinger / RSI / VWAP bands)

| | |
|--|--|
| **What** | Fade stretched moves into prior value / VWAP when regime = range |
| **Edge** | High win-rate in sideways regimes |
| **Needs** | Reliable regime detector (critical) |
| **Fails when** | Strong trend days (catching knives) |
| **Learnable knobs** | Z-score thresholds, only fade if Plan B confidence low |

### Plan D — Options defined-risk (debit spreads / long premium with structure)

| | |
|--|--|
| **What** | Express Plan A/B bias with **defined max loss** (verticals) instead of naked futures size |
| **Edge** | Caps blow-ups; better capital efficiency for directional bets |
| **Needs** | Chain / strike map, lot size, expiry calendar, IV sanity |
| **Fails when** | IV crush wrong-way, wide spreads / liquidity |
| **Learnable knobs** | DTE, delta target, max debit, avoid expiry-day |

### Plan E — Event / Volatility breakout (straddle-ish or expansion after compression)

| | |
|--|--|
| **What** | Trade expansion after low ATR compression or known event window (with Market Brief risk regime) |
| **Edge** | Big days after quiet coils |
| **Needs** | ATR percentile, event calendar / news brief flags |
| **Fails when** | Expansion fakes then dies (theta + whip) |
| **Learnable knobs** | Compression lookback, which events to skip vs trade |

---

## 3. Deduction — the single best architecture

### Verdict

**Do not pick only A or only B forever.**

Ship **FRIDAY Meta-Engine** with:

1. **Primary book (V1):** Plan A + Plan B on **index futures** (Nifty → BankNifty)  
2. **Secondary book (V1.5):** Plan C **only when regime = RANGE** (hard gated)  
3. **Options book (V2):** Plan D as risk wrapper / alternate expression  
4. **Event overlay (V2):** Plan E as *permission / veto*, not always-on spam  
5. **Meta-controller:** Chooses which book is allowed **this session / this hour**, and learns weights from saved results  

```
                    ┌──────────────────────────┐
   Live feeds  ───► │  REGIME DETECTOR         │
   Zerodha/Groww    │  trend | range | event   │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  STRATEGY ROUTER         │
                    │  A/B/C/D/E allow masks   │
                    │  + learned weights       │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
         Signal A/B          Signal C           Signal D/E
              │                  │                  │
              └────────────┬─────┴──────────────────┘
                           ▼
                 ┌─────────────────────┐
                 │  RISK + OMS         │
                 │  paper → approve    │
                 │  → Groww LIVE       │
                 └──────────┬──────────┘
                            ▼
                 ┌─────────────────────┐
                 │  MEMORY (saved)     │
                 │  outcomes → weights │
                 │  Claude postmortem  │
                 └─────────────────────┘
```

### Why this beats “one algo”

| One fixed algo | FRIDAY Meta |
|----------------|-------------|
| Great in one regime, dies in another | Switches allow-mask by regime |
| Manual retune forever | Saves trades → updates weights / vetoes |
| LLM as magic trader | Claude = regime narrative, veto, postmortem — **not** raw order authority |
| No feedback loop | Closed loop with MyTrade F&O journal |

### Learning model (practical, not fantasy ML day-one)

**Phase 1 learning (ship first):**

- Store every intent: features snapshot, strategy id, regime, decision, fill, P&amp;L, MAE/MFE  
- Score strategies by **expectancy + drawdown + recent 20 trades**  
- Softmax / rank weights → router prefers winners **in matching regime**  
- Auto-disable a strategy if rolling expectancy &lt; 0 for N trades in that regime  

**Phase 2 learning:**

- Parameter bandit / walk-forward on knobs (ORB minutes, ATR mult) inside safe ranges  
- Claude weekly “FRIDAY briefing”: which rules to tighten (human approve before apply)  

**Phase 3 (optional later):**

- Lightweight model on features → P(win) as a **filter**, never sole trigger  

**Hard rule:** Learning may change **weights, filters, and params within bounds** — never remove kill switch, max loss, or mode gates.

---

## 4. Claude Code CLI role (“behind the screen”)

TRADELE already supports `LLM_PROVIDER=claude_cli` (Claude Code CLI via `claude auth login` — see `.env.example`).

### What Claude **does**

| Job | Input | Output |
|-----|--------|--------|
| **Regime narrative** | Live feature JSON + Market Brief flags | `trend\|range\|event` + confidence + why |
| **Setup critique** | Candidate signal + chart stats | Approve / veto / reduce size (suggestion) |
| **Conflict resolution** | A says long, C says fade | Prefer router; Claude explains |
| **Post-trade review** | Fill + path of price | Lessons → structured tags saved |
| **Weekly evolution proposal** | Aggregated Memory | Proposed param diffs (needs human accept) |

### What Claude **must never** do

- Call Groww `place_order` directly  
- Override kill switch / daily loss / max lots  
- Invent symbols not in contract map  
- Trade without a rules-engine primary signal (Claude is **advisor**, rules are **authority** for V1–V2)

### Invocation pattern

```
Scheduler / tick loop
  → build FridaySnapshot (quotes, candles, positions, regime features)
  → rules strategies emit candidates
  → call_llm_auto(structured prompt) via Claude CLI
  → merge: rules MUST fire; Claude can only VETO or SIZE_DOWN (config)
  → OMS risk gates → paper / approve / live
```

Keep prompts **JSON-in / JSON-out**, temperature low, and log full traces for audit.

---

## 5. Live data plane (APIs)

### Eyes — Zerodha (primary market data)

| Data | Use in FRIDAY |
|------|----------------|
| NFO instruments | Contract map, lot size, expiry |
| LTP / quote | Triggers, marks |
| Historical minute / 5m | ORB, VWAP, structure, ATR |
| (Later) KiteTicker WS | Lower latency triggers |

### Hands + truth — Groww

| Data | Use in FRIDAY |
|------|----------------|
| Positions / orders / trades | Reconcile, journal, learning labels |
| Historical candles (FNO) | Fallback if Kite gaps |
| **place / modify / cancel** *(to build)* | Execution |
| Margins / funds *(if available)* | Size caps |

### Own memory — TRADELE DB / MyTrade

| Data | Use |
|------|-----|
| F&amp;O P&amp;L calendar & day review | Outcome ground truth |
| Trader DNA / journal fills | Personal veto patterns |
| Market Brief risk regime | Event / risk-off overlay |
| `FridayMemory*` tables | Strategy weights, param versions |

### Symbol map (non-negotiable)

Zerodha `NFO:…` ↔ Groww FNO trading symbol must be **exact**; reject on ambiguity.

---

## 6. System architecture

```
TRADELE FRIDAY
├── Feed Hub          Zerodha MD + Groww account + Brief
├── Feature Store     session bars, VWAP, ATR, ORB, OI later
├── Regime Detector   rules first + Claude narrative
├── Strategy Pack     A, B, C, (D, E)
├── Meta Router       allow-mask + learned weights
├── Claude Advisor    veto / size-down / explain
├── Risk Governor     limits, windows, freshness
├── OMS               intents → Groww orders
├── Reconciler        OMS book == Groww positions
├── Memory            save → score → adapt
└── Desk UI           modes, kill, intents, health
```

### Modes

| Mode | Behavior |
|------|----------|
| `OFF` | No signals |
| `PAPER` | Full pipeline, simulated fills, Memory learns |
| `SHADOW` | Parallel to your manual F&amp;O; compare |
| `APPROVE` | Live ready but human confirms each intent |
| `LIVE` | Armed auto within risk caps |

---

## 7. Risk & safety (before any LIVE)

| Gate | Rule |
|------|------|
| Kill switch | Flatten + block new intents |
| Max daily loss | ₹ and % hard stop → force `OFF` |
| Max lots / underlying | Cap |
| Max concurrent strategies | e.g. 1 directional book at a time |
| Trading window | 09:20–15:10 IST (config) |
| Feed freshness | Stale quote → no entry |
| Reconcile mismatch | Pause |
| Arm LIVE | Explicit confirm + secret / password |
| Claude outage | Rules-only continue **or** pause (config; default: pause new entries) |

---

## 8. Phased development plan

### Phase 0 — Foundations & go/no-go (about 1 week)

- [ ] Lock name **FRIDAY** in docs / future modules  
- [ ] Confirm Groww FNO **create order** API against current Trade API docs  
- [ ] Confirm Zerodha NFO quotes + candles on your Kite access  
- [ ] Broker / compliance: API algo use allowed on your Groww account  
- [ ] Define capital, max daily loss, underlyings (start **Nifty futures only**)  

**Exit:** Written go/no-go.

### Phase 1 — Observation + Memory (no orders) — “FRIDAY listening”

- [ ] NFO instrument sync + contract map skeleton  
- [ ] Live/near-live feature builder (ORB, VWAP, ATR, structure)  
- [ ] Implement Strategy A + B signal emitters (paper)  
- [ ] Regime detector v1 (rules)  
- [ ] `FridayMemory` schema: snapshots, intents, outcomes  
- [ ] Desk UI stub: feed health, paper intents, regime badge  
- [ ] Claude advisor in **explain-only** mode  

**Exit:** 2+ weeks paper log you can inspect in UI.

### Phase 2 — Meta-router + learning loop

- [ ] Strategy C gated by RANGE regime  
- [ ] Weight updater from paper expectancy by regime  
- [ ] Auto-disable / re-enable rules  
- [ ] Claude postmortem tags into Memory  
- [ ] Shadow vs your manual Groww F&amp;O days  

**Exit:** Router clearly changes behavior across trend vs chop days.

### Phase 3 — Groww OMS (approve → tiny LIVE)

- [ ] Groww place / cancel / status wrappers  
- [ ] OMS state machine + idempotent `intent_id`  
- [ ] Risk governor + kill switch wired to UI  
- [ ] `APPROVE` mode first; then `LIVE` at **1 lot**  
- [ ] Reconciler + MyTrade F&amp;O journal linkage  

**Exit:** 10+ live fills, zero unexplained position drift.

### Phase 4 — Options (Plan D) + Event overlay (Plan E)

- [ ] Strike selection helpers + defined-risk only  
- [ ] Market Brief / event veto integration  
- [ ] Weekly Claude evolution proposals (human apply)  

### Phase 5 — Hardening

- [ ] Websocket feeds, latency SLOs  
- [ ] Chaos: token expiry, partial fills, reject storms  
- [ ] Audit export, Telegram alerts (optional)  
- [ ] Param bandit within safe bounds  

---

## 9. Proposed codebase layout

```
TRADELE/services/friday/
  __init__.py
  modes.py                 # OFF/PAPER/SHADOW/APPROVE/LIVE
  snapshot.py              # FridaySnapshot builder
  feeds_zerodha.py
  feeds_groww.py
  contracts.py             # NFO map
  features.py
  regime.py
  strategies/
    orb_a.py
    trend_b.py
    meanrev_c.py
    options_d.py
    event_e.py
  router.py                # meta weights + allow-mask
  advisor_claude.py        # Claude CLI structured advise
  risk.py
  oms.py
  paper.py
  memory.py                # save / score / adapt
  reconcile.py

TRADELE/api/routes/friday.py
UI/src/pages/Friday.tsx    # desk (evolve from Fno.tsx)
docs/FRIDAY_PLAN.md        # this file
```

### Config sketch

```env
FRIDAY_MODE=OFF
FRIDAY_UNDERLYINGS=NIFTY
FRIDAY_MAX_DAILY_LOSS=5000
FRIDAY_MAX_LOTS=1
FRIDAY_CLAUDE_ROLE=veto_and_explain   # explain_only | veto_and_explain
FRIDAY_ARM_SECRET=...
LLM_PROVIDER=claude_cli
LLM_FALLBACK=gemini,openai
```

---

## 10. Data we save (learning fuel)

Every intent row should store enough to retrain knobs later:

- `ts`, `underlying`, `strategy_id`, `regime`, `features_json`  
- `side`, `qty`, `entry_ref`, `stop_ref`, `target_ref`  
- `claude_verdict`, `claude_reason`  
- `mode` (paper/live), `broker_order_ids`  
- `fill_px`, `exit_px`, `pnl`, `mae`, `mfe`, `hold_secs`  
- `outcome_tags` (stop_hit, target_hit, time_exit, vetoed, rejected)  

Nightly job: recompute strategy scorecards → write `FridayWeightSnapshot`.

---

## 11. Success metrics (review gates)

| Gate | Metric |
|------|--------|
| Paper edge | Expectancy &gt; 0 after assumed slippage/costs |
| Regime skill | A/B outperform on trend days; C not blown up on trend days |
| Learning | Disabled strategies show worse forward paper than active ones |
| Ops | Reject rate low; reconcile errors = 0 before size-up |
| Safety | Kill switch tested weekly; daily loss never breached in LIVE |

If paper edge dies under realistic slippage → **do not** arm LIVE.

---

## 12. Explicit non-goals (keep FRIDAY strong)

- HFT / co-location fantasies  
- Naked short options in V1–V2  
- Claude-only trading with no rules signal  
- Dual execution on Zerodha + Groww  
- “Set and forget” without kill switch / daily loss  

---

## 13. Review checklist (for you)

Please mark decisions so implementation can start cleanly:

1. **Name:** FRIDAY — confirmed?  
2. **V1 underlying:** Nifty futures only, or Nifty + BankNifty?  
3. **Claude role day-one:** `explain_only` or `veto_and_explain`?  
4. **Autonomy path:** PAPER → APPROVE → LIVE — OK?  
5. **Max daily loss / max lots** for first LIVE?  
6. **Strategy pack:** Agree Meta (A+B primary, C gated, D/E later)?  
7. **Replace `/fno` placeholder** with FRIDAY desk, or new `/friday` route?

---

## 14. Recommended immediate next step (after your review)

1. Approve this plan + checklist answers.  
2. Phase 0 spike: Groww place-order docs + one Nifty fut quote path.  
3. Scaffold `services/friday/` in **PAPER + explain_only** — no LIVE code paths armed by default.

---

## Appendix A — Mapping Avengers metaphor → modules

| Marvel vibe | FRIDAY module |
|-------------|----------------|
| Eyes / HUD | Zerodha feed hub |
| Hands / suit actuators | Groww OMS |
| Friday (AI) | Claude advisor + Memory |
| Suit protocols | Risk governor + modes |
| Mission logs | MyTrade F&amp;O journal + FridayMemory |

## Appendix B — Why not “only ML” or “only ORB”

| Approach | Problem |
|----------|---------|
| Only ORB | Dies in chop; no adaptation |
| Only ML black box | Hard to trust, easy to overfit, weak audit |
| Only Claude | Non-deterministic; unsafe for money |
| **FRIDAY Meta** | Auditable rules + regime switch + saved learning + Claude veto |

---

*End of plan — awaiting your review comments.*
