# Road to Real Money

Everything between the current state and the point where it would be reasonable to
risk actual money: the interface restructure, agent autonomy, the safety engineering,
and the proof.

Nine phases across four stages, ordered by dependency. Each stage is a sensible
stopping point — you can sit at the end of any of them indefinitely without leaving
something half-finished.

Last updated: 29 August 2026.

---

## Settled decisions

**Stay on Vercel. Stay on OANDA.**

The site is already online 24/7 — Vercel does not sleep it. What stops when nobody has
a tab open is the *scheduled job*, and on the free plan that can only run once a day.
A free external scheduler calling the endpoint that already exists closes that gap at
no cost.

Staying with OANDA also means the app may never need to leave Vercel. OANDA's stops sit
at the broker, so nothing needs to watch prices continuously, and every call is an
ordinary web request. Pepperstone is genuinely cheaper to trade — roughly 0.35 pips
all-in on EUR/USD against OANDA's ~1.6 — but their API requires a permanently open
socket, which serverless cannot hold. At 1,000 units that spread gap is about 12p per
round trip; it only justifies the rebuild at standard-lot size, where it is closer to
£12.50 a trade.

| Option | Cost | Verdict |
| --- | --- | --- |
| Vercel + external cron | Free | Calls the existing endpoint from outside Vercel, so the once-a-day cap stops mattering. No migration. **Start here.** |
| Vercel Pro | $20/mo | Native scheduling to the minute, longer time limit per job. Worth it if the scan job cannot finish inside the free plan's 10-second cap. |
| Fly.io / Render | $2–7/mo | A genuinely always-on process. Only needed for a broker that demands a persistent connection — which OANDA does not. |

Costs are US dollars as listed by each provider, checked August 2026.

---

# Stage 1 — Make the agent real

## Phase 1: Run without a browser open

Everything else assumes an agent you can leave alone. Today that is not true, and not
because of the strategy.

1. **Schedule the stop and target check.** The endpoint exists and is already protected
   by `CRON_SECRET` — it was built for this. Point a free external scheduler at it every
   5 minutes during market hours. No code changes.
2. **Build the scan-and-open job.** *Blocker.* Nothing currently opens a trade unless
   someone clicks "Run Full Scan" in the UI. There is no scheduled equivalent, so an
   unwatched agent closes trades but never takes any. Needs a scheduled endpoint that
   scans the watchlist and opens qualifying trades while respecting the kill switch,
   risk limits, trading window, news blackout and duplicate guard that already exist.
3. **Test against the 10-second function limit.** Six pairs of live data may not finish
   inside the free plan's cap. If not: split to one pair per run, or move to Pro.
   Measure before paying.
4. **Add a heartbeat.** Record when the agent last ran and what it decided. Without it,
   "the scheduler broke three days ago" and "there were no good setups" look identical —
   exactly the failure mode you cannot afford in something you have stopped watching.

## Phase 2: Controls and the broker seam

1. **Put the broker behind one interface.** Only five functions actually talk to OANDA —
   quotes, candles, place order, close position, list positions — roughly 100 lines in
   total. Formalising that boundary costs very little now, lets execution logic be tested
   without touching a broker, and keeps the door open if OANDA's spreads are ever
   outgrown.
2. **Agent controls in Settings.** On/off, which pairs may be traded unattended, scan
   frequency, and the maximum number of concurrent positions. These are currently decided
   in code rather than by the operator.
3. **Run the trade history repair.** Already built and live, but it only corrects
   existing records when run from Settings. Preview first, then apply.

---

# Stage 2 — Rebuild the interface

## Phase 3: Journal onto its own tab

Cheapest piece of the restructure, and the right place to set the pattern the other tabs
follow.

1. **New tab, move the journal into it.** Relocation of a panel that already works.
2. **Day and week summaries.** Group closed trades by date with totals per day and week.
   The underlying stats already exist — presentation, not new maths.
3. **Set the stylesheet rule for new tabs.** Three bugs in a single session came from
   seven stylesheets overriding each other with `!important`: the dashboard appearing on
   every tab, the header forcing the page to 751px on mobile, and the risk card divider.
   New tabs get their own scoped stylesheet rather than joining that pile.

## Phase 4: Manual trading tab

The MT4-style page: chart, live P&L, quick buys and sells, fast closes. The biggest
build, and the one used daily.

1. **New tab; chart and trade ticket move here.** Also stop loading the charting library
   on every page — it is currently pulled in everywhere whether a chart is shown or not.
2. **Live running P&L.** *New build.* Profit is currently only calculated when a trade
   closes; there is no floating P&L on open positions. Needs per-position running profit
   plus an account summary strip. Inputs exist: position size is stored on every trade and
   there is a live price feed.
3. **Fix personal trades not drawing on the chart.** Likely the chart filters which trades
   it draws and personal ones do not match. Right place to fix it is here, where they are
   the point of the page.
4. **One-action close from the position row**, rather than finding the trade in a dropdown.

## Phase 5: Agent tab and the comparison

Mostly relocation, which is why it follows the manual tab that receives the chart.

1. **Scanner and agent activity together, no chart.** The agent reads prices straight from
   the feed and never used the chart to decide anything, so removing it costs nothing.
2. **Live AI positions, journal-style.** Open trades with entry, stop, target and running
   result, plus the decision log. Closed trades appear in the journal — nothing moves, a
   trade is one record that flips from open to closed.
3. **AI vs Manual P&L.** Every trade already records who placed it, so this is grouping
   existing data. One shared wallet, two figures. Show average R beside the pounds: if the
   agent risks 0.5% and manual trades are larger, the pound figures flatter whoever risked
   more and say nothing about who traded better.

---

# Stage 3 — Make it safe for money

## Phase 6: Make the paper results honest

A real-money decision will be made from these numbers, so the numbers must not be
flattering. Everything here makes results *worse* — that is the point.

1. **Model slippage on stops.** Stops currently fill at exactly their level. Real ones slip
   past it, especially on gold and around news. Today this makes paper results mildly
   optimistic.
2. **Weekend and gap handling.** A position held over the weekend can reopen far past its
   stop, and the fill-at-stop assumption is most wrong exactly there. Decide whether the
   agent flattens before the close or accepts gap risk explicitly.
3. **Maximum holding period.** Nothing currently forces a trade to end. A position that
   hits neither stop nor target can sit open indefinitely, blocking that pair.
4. **Confirm all costs are counted.** Spread is already charged correctly — trades buy at
   the ask and sell at the bid using real quotes. Overnight financing on positions held
   past the daily rollover is not currently accounted for.

## Phase 7: Live-readiness engineering

The work separating a paper simulation from something allowed near a funded account.
None of it is optional, and none of it depends on the choice of broker.

1. **Reconcile against the broker.** The single most important item. In paper trading the
   app's records *are* the truth. With real money the broker is the truth, and the two
   drift — an order fills after a timeout, a position closes at the broker while the app
   still shows it open. Every run should compare its own view against the broker's actual
   positions and flag mismatches loudly.
2. **Make order placement idempotent.** If the network drops after an order is sent but
   before the reply arrives, a naive retry opens a second position. Every order needs a
   unique key so a repeat cannot double-place it.
3. **Handle rejections and partial fills.** Real brokers refuse orders — insufficient
   margin, market closed, price moved too far — and sometimes fill only part of one.
   There is currently no path for either; the code assumes the order works.
4. **Decide what happens when the broker is unreachable.** Fail safely and visibly rather
   than silently skipping. Retry with backoff, then stop and report.
5. **Alerting.** With real money, breakage, trade opens and loss-limit trips need to be
   known within minutes — not the next time the tab happens to be open.
6. **A kill switch that works on live positions.** It currently stops new paper trades. On
   live it must also be able to flatten what is already open, and be reachable from a
   phone in seconds.
7. **Separate live credentials and deliberate friction.** Live keys kept apart from
   practice keys, live mode impossible to enable by accident, and a hard cap on position
   size the agent cannot exceed whatever the strategy asks for. Live trading is
   deliberately locked in the code today (`MODE_LIVE` in `backend/execution.py`); that
   lock should only ever open on purpose.

---

# Stage 4 — Prove it, then go live

## Phase 8: Prove the strategy

Engineering readiness and strategy readiness are different things. This is the one that
cannot be rushed, because it is mostly waiting.

1. **Out-of-sample validation.** *Outstanding.* The calibrated per-pair settings were
   fitted on the same history they were then judged against, which flatters them by
   construction. They need testing on a period they have never seen. Until then, treat the
   calibration as promising rather than proven.
2. **Forward test on a fixed configuration.** A real stretch of live-data paper trading
   with settings that are not touched. Changing parameters mid-test restarts the clock —
   the point is to watch the strategy fail and recover without intervention.
3. **Decide EUR/GBP's place on the watchlist.** Flagged as the weakest performer. Either it
   earns its slot on the calibrated settings or it comes off.
4. **Review the drawdown, not just the profit.** The number that decides whether this is
   liveable is the worst losing run, not the total.

## Phase 9: Go live, small

1. **Smallest size the broker allows, one pair.** The first live weeks test the plumbing,
   not the strategy. Position size should be small enough that losing every trade would
   not matter.
2. **Run live and paper side by side.** Same signals in both. Where live results differ
   from paper, that difference is the real slippage and cost — worth measuring rather than
   assuming.
3. **Scale only on evidence.** Increase size on results, not confidence. Set the thresholds
   in advance, while calm.
4. **Records for tax.** The journal already holds what is needed — make sure it exports,
   and check the UK tax position before rather than after.

---

## Ready when all of these are true

The Paper Mode notice in the app already states its own bar. This is that list, plus what
the recent work added.

- [ ] The agent has run unattended for a sustained period without being rescued — *Phases 1, 8*
- [ ] Positive expectancy after realistic spreads, slippage and financing — *Phase 6*
- [ ] The strategy has been tested on data it was not tuned on — *Phase 8.1, outstanding*
- [ ] Worst drawdown is known, and acceptable in pounds — *Phase 8.4*
- [ ] The app reconciles against the broker and reports disagreement — *Phase 7.1*
- [ ] Orders cannot be double-placed, and rejections are handled — *Phases 7.2, 7.3*
- [ ] Breakage is reported within minutes — *Phase 7.5*
- [ ] The kill switch can flatten live positions from a phone — *Phase 7.6*
- [ ] The journal is complete, auditable and exportable — *Phase 3*
- [ ] No hard risk rule breached during the forward test

**Worth being blunt about.** Stages 1 and 2 are the enjoyable part and roughly a fifth of
the work. Stage 3 is unglamorous and non-negotiable. Stage 4 is mostly waiting — the
forward test cannot be compressed by working harder. The common way a project like this
loses money is not a bad strategy; it is a good strategy attached to software that quietly
stopped doing what its owner assumed it was doing.

---

## Open decisions

| Question | Status |
| --- | --- |
| One wallet or two? | **Settled** — one shared wallet, P&L reported separately. Avoids splitting risk limits, sizing and deposits for a number that only needs looking at. |
| Broker and host? | **Settled** — OANDA on Vercel. Revisit only at standard-lot size. |
| How often should the agent scan? | Open. Every 5 minutes is responsive and within free limits; every 15 is gentler and probably makes no difference on an hourly-candle strategy. |
| Which pairs may it trade unattended? | Open. Worth starting narrow — an unwatched agent trading gold on a tight stop is the highest-variance thing in the system. |
| Trade only inside the London window? | Open. The logic exists; the question is whether the scheduled agent respects it strictly or may still manage existing positions outside it. |

---

## Parked

- **The phone crash.** Never reproduced — production is not reachable from the build
  environment and iOS uses a browser engine that could not be tested there. Removing the
  chart from most pages in Phase 4 may resolve it as a side effect. **This must be fixed
  before live:** a kill switch that cannot be reached from a phone is not a kill switch.
  The diagnostic that would settle it is whether `/api/health` loads on the phone.
- **Strategy version history.** Six calibrated configurations are saved. Confirm the right
  one is active per pair before the forward test begins — the test is only meaningful on a
  fixed configuration.

---

*Nothing here is financial advice. The strategy, the risk limits and the decision to trade
real money are the operator's.*
