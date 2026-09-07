# Road to Real Money

Everything between the current state and the point where it would be reasonable to
risk actual money: the interface restructure, agent autonomy, the safety engineering,
and the proof.

Eight phases across four stages, ordered by dependency. Each stage is a sensible
stopping point — you can sit at the end of any of them indefinitely without leaving
something half-finished.

Last updated: 7 September 2026.

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

Everything else assumes an agent you can leave alone.

1. ~~**Schedule the stop and target check.**~~ **Done.** cron-job.org calls
   `/api/agent/cron/auto-close` every 5 minutes and `/api/agent/cron/scan-open` every 15,
   both authenticated with `CRON_SECRET`. Note both run 7 days a week — the market-closed
   guard, not the schedule, is what keeps the agent out of the weekend.
2. ~~**Build the scan-and-open job.**~~ **Done.** `/api/agent/cron/scan-open` scans the
   watchlist and opens qualifying trades, gated on: agent enabled, kill switch, real
   daily and weekly loss limits, the trading window, max concurrent positions, max trades
   per day, a confidence floor, the duplicate guard, and a refusal to trade on fallback
   prices. Also runnable from Settings, with a dry-run mode.
3. **Test against the 10-second function limit.** *Still to check.* Six pairs of live data
   may not finish inside the free plan's cap. If not: split to one pair per run, or move
   to Pro. Measure before paying — the first live cron run will show it.
4. ~~**Add a heartbeat.**~~ **Done.** Every run is recorded — what it scanned, what it
   opened, what it skipped and why, and why it stood down. Visible in Settings and at
   `/api/agent/agent-runs`.

## Phase 2: Controls and the broker seam

1. **Put the broker behind one interface.** Only five functions actually talk to OANDA —
   quotes, candles, place order, close position, list positions — roughly 100 lines in
   total. Formalising that boundary costs very little now, lets execution logic be tested
   without touching a broker, and keeps the door open if OANDA's spreads are ever
   outgrown.
2. ~~**Agent controls in Settings.**~~ **Done.** On/off, allowed pairs, strategies, max
   open trades, max trades per day, confidence floor, and whether to respect the London
   window. Plus a dry run and a run-now button.
3. **Run the trade history repair.** ~~Outstanding~~ **Done** — applied, correcting 13
   trades. The numbers it produced exposed the synthetic-price bug fixed in #57.

---

# Stage 2 — Rebuild the interface

Layout agreed 7 September 2026 from the mockup. Four tabs become two working ones:
**Trade** for doing it, **Dashboard** for reviewing it. Performance and Settings stay
as they are.

The reason for the merge is that finding a setup and taking it were two screens apart,
and reviewing what happened sat on top of the screen used to trade. Splitting by *job*
rather than by *feature* fixes both.

## Phase 3: The Trade tab

Receives the chart, the ticket and the scanner. The biggest build and the one used daily.

1. **Move the chart and ticket here; fold the scanner in underneath.** Scanner candidates
   sit below the chart rather than beside it, so the chart stays wide — six pairs fit
   across without either being cramped. Each candidate carries a *Take setup* button that
   opens it directly, stamped `scanner_manual_execute` so it reads **Manual-Scanner**.
2. **Retire the standalone Scanner tab.** Its scan history moves to Performance, which is
   where the other retrospective views already live.
3. **The ticket shows the side it fills on.** A sell fills at the bid, a buy at the ask —
   the same rule the journal and chart already use. Showing the mid here would put the
   one screen that opens trades out of step with every screen that reports them.
4. **News guard line under the button.** Already built; needs surfacing here rather than
   only on the Calendar tab. A blackout matters in the second before you click.
5. **One-action close from the position row**, rather than finding the trade in a dropdown.
6. **Fix personal trades not drawing on the chart.** The chart likely filters which trades
   it draws and hand-placed ones do not match. Right place to fix it is here.
7. **Stop loading the charting library on every page.** It is currently pulled in
   everywhere whether a chart is shown or not, and it is the single heaviest asset — a
   plausible contributor to the unreproduced phone crash.

## Phase 4: The Dashboard tab

Receives the journal. Mostly relocation of panels that already work.

1. **Move the journal here.** It is a review surface, not a trading one.
2. **Agent vs you, three ways.** `by_origin` already returns AGENT TRADE, Manual-Scanner
   and Personal with their own R, win rate and drawdown. Surface it. Show average R beside
   the pounds: if the agent risks 0.5% and hand-placed trades are larger, the pound figures
   flatter whoever risked more and say nothing about who traded better.
3. **Day and week summaries.** Group closed trades by date with totals. The maths exists.
4. **Give the new tabs their own scoped stylesheet.** Three bugs in a single session came
   from seven stylesheets overriding each other with `!important`: the dashboard appearing
   on every tab, the header forcing the page to 751px on mobile, and the risk card divider.
   New work does not join that pile.

# Stage 3 — Make it safe for money

## Phase 5: Make the paper results honest

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
4. **Confirm all costs are counted.** Spread is now charged on both sides: live trades
   fill at the executable price, and the backtest charges one round trip per trade, so a
   stop-out costs about -1.11R rather than exactly -1.00R. Overnight financing on positions
   held past the daily rollover is still not accounted for.

## Phase 6: Live-readiness engineering

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
5. ~~**Alerting.**~~ **Done.** Trade opens, loss-limit halts and total data failure post
   to a webhook of your choosing (ntfy for phone push, or Discord/Slack). Routine
   stand-downs stay silent so the alerts keep meaning something. Still needs one real
   end-to-end test from Settings → Send Test Alert.
6. **A kill switch that works on live positions.** It currently stops new paper trades. On
   live it must also be able to flatten what is already open, and be reachable from a
   phone in seconds.
7. **Separate live credentials and deliberate friction.** Live keys kept apart from
   practice keys, live mode impossible to enable by accident, and a hard cap on position
   size the agent cannot exceed whatever the strategy asks for. Live trading is
   deliberately locked in the code today (`MODE_LIVE` in `backend/execution.py`); that
   lock should only ever open on purpose.
8. **Close the front door.** `TEMP_PASSWORDLESS_LOGIN` defaults to **true**, so anyone
   who names an allowed user logs in with no passcode — and `AUTH_ALLOWED_USERS` defaults
   to `Jake,Jordan`. That is deliberate while the site is unannounced and nothing is at
   stake, and it must be off before a funded account exists. Flipping the default in
   `backend/auth.py` locks out anyone who does not know `AUTH_PASSCODE`, so set and
   confirm that passcode first. A "keep me logged in" option belongs with this change,
   or the friction will tempt it back off.
9. **Connect an economic calendar.** The news guard itself is built
   (`backend/news_guard.py`): it blacks out a configurable window either side of
   high-impact releases for both currencies in a pair, gold included via USD, and it
   refuses to trade rather than guess when the calendar cannot be reached. It stays off
   and says so until a provider is configured. Either
   `ECONOMIC_CALENDAR_PROVIDER=finnhub` with `ECONOMIC_CALENDAR_API_KEY`, or
   `ECONOMIC_CALENDAR_URL` pointed at any endpoint returning JSON. Both field
   conventions are handled, so a free ForexFactory-style weekly feed needs no code
   change. **Check the cost before relying on a provider** — Finnhub gates several
   endpoints behind its paid plans and this may be one of them; a provider that starts
   refusing requests stops the agent trading, by design. Until a calendar is connected,
   nothing stops the agent opening straight into NFP.
10. **Give previews their own database.** Preview deployments do not inherit
   Production-scoped environment variables, but they *do* share `DATABASE_URL` — so a
   build with no market-data credentials reads and writes the real wallet. Opening trades
   from such a deployment is now blocked (`market_data_is_live()`), but the cleaner fix is
   a separate database for previews so they cannot touch production data at all.

---

# Stage 4 — Prove it, then go live

## Phase 7: Prove the strategy

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

## Phase 8: Go live, small

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

- [ ] The agent has run unattended for a sustained period without being rescued — *Phases 1, 7*
- [ ] Positive expectancy after realistic spreads, slippage and financing — *Phase 5*
- [ ] The strategy has been tested on data it was not tuned on — *Phase 7.1, outstanding*
- [ ] Worst drawdown is known, and acceptable in pounds — *Phase 7.4*
- [ ] The app reconciles against the broker and reports disagreement — *Phase 6.1*
- [ ] Orders cannot be double-placed, and rejections are handled — *Phases 6.2, 6.3*
- [ ] Breakage is reported within minutes — *Phase 6.5*
- [ ] The kill switch can flatten live positions from a phone — *Phase 6.6*
- [ ] The journal is complete, auditable and exportable — *Phase 4*
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
| How often should the agent scan? | Open. Vercel's free plan runs the scan once a weekday at 09:30 UTC. An external scheduler can make it every 5 minutes for free. |
| Which pairs may it trade unattended? | Settable in Settings. Worth starting narrow — an unwatched agent trading gold on a tight stop is the highest-variance thing in the system. |
| Trade only inside the London window? | **Settled — off.** Neither the backtest nor the calibrator ever filtered by session, so the settings were fitted on all-hours data. Running 24/5 matches what was actually tested; the London-only restriction did not. Still switchable in Settings. |
| Which strategies? | Settable per pair, or globally for the agent. Trend continuation is the default; mean reversion is opt-in and unproven. |

---

## Parked

- **The phone crash.** Never reproduced — production is not reachable from the build
  environment and iOS uses a browser engine that could not be tested there. Removing the
  chart from most pages in Phase 3 may resolve it as a side effect. **This must be fixed
  before live:** a kill switch that cannot be reached from a phone is not a kill switch.
  The diagnostic that would settle it is whether `/api/health` loads on the phone.
- **Strategy version history.** Six calibrated configurations are saved. Confirm the right
  one is active per pair before the forward test begins — the test is only meaningful on a
  fixed configuration.

---

*Nothing here is financial advice. The strategy, the risk limits and the decision to trade
real money are the operator's.*
