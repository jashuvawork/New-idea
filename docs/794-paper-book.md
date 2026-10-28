# The #794 paper book

What was asked for, what landed on `main`, and what the server is actually running.

_Checked 28 Oct 2026, 14:15 Madrid (18:45 IST). Market was already closed._

## The book that was asked for

One paper book. Live trading stays off. The 21 October #794 tree stays whole, and the original #676 pad is not edited.

| Piece | What it does | Where it came from |
|---|---|---|
| #794 tree | The 21 October book, restored as a whole | #870, commit `ef333c95` is the #794 exit commit the pad sits on |
| #676 pad | Unchanged. A call at the base still gets the +44 rank bonus. A put still takes the −36 rank penalty. Chop can still waive. `backend/app/engines/best_trade_policy.py` matches `ef333c95` byte for byte | Kept on purpose. #869, which would have given a put the same pad, was closed and is not in this book |
| #816 exits | A fall through the 75% line can sell after 45 seconds under that line. The runner keeps its profit guard. On a mega leg the take-profit rungs own the exit, ahead of a between-rung fade above 55 points. Booked profit still stage-locks | #816, carried in the 28 Oct deploy |
| Today's index open | The helper uses today's cash open. A pre-open print, a chart open from an older window, and the first tick after a restart are not today's open | Live index-open fix |
| Cash-candle hold | 09:15–09:45 IST. Three closes stepping off the extreme, with a 0.04% giveback, block the side. This votes before the index macro | #865 |
| Open macro | 09:25–09:45 IST only. Idle before 09:25 and at or after 09:45, so the cash-candle hold owns 09:15–09:24. The first order is still 09:20 | #867 |
| Fresh-base reentry | One more entry on the same strike after a win, only off a fresh rising base, and only inside the 22% pad. A fading print, a second leg, the other side, and a chase past the pad stay blocked | #866 |
| Hang fixes | The October loop-hang guards stay. They do not change the pad | Oct 13 fixes, kept while the pad was restored |
| Restart memory | After a restart, a closed trade keeps its points, its best points, and its peak. A winner must not come back as a flat trade | #872 |
| One trader pass | A chain rebuild refreshes the chain. It does not run a second trader pass on top of the live scan. If a pass is already running, the next one returns instead of waiting behind it | #872 |

Paper is the execution mode: `ENABLE_LIVE_TRADING=false`, `PAPER_TRADING=true`, broker orders simulated. Sizing capital is ₹2,00,000. The option premium band is ₹18–₹350. That ₹350 cap is the live gate. The closed #806 change, which would have raised it to ₹450, is not part of this book.

## How the open is supposed to behave

All times are IST.

1. **09:15–09:24.** The cash-candle hold can block a side. The index macro is idle. No order before 09:20.
2. **09:25–09:44.** The cash-candle hold still applies. The index macro also applies: the index has to have moved off today's open in the trade's direction, and price has to sit in that side's half of today's range.
3. **09:45 onward.** Both open checks are idle. The rest of the book, including the #676 pad and the #816 exits, keeps running.

## What is aligned

`main` at `df294b91` is this book.

- The tree is the same tree as the #872 branch.
- `best_trade_policy.py` has no diff against `ef333c95`.
- `deploy/env.production.template` is paper, with live trading off.
- The live flags that are already on the server match the clocks and the band: first order 09:20, open caution until 09:45, premium ₹18–₹350, sizing ₹2,00,000, paper on, live off.

These pull requests were closed because they are not part of the book: #806 (₹450 premium cap), #809 (a separate ₹2L sizing change; ₹2L is already the book), #843 (turn the 09:15–09:45 index check off), #862 (the #816 pack as its own branch; the pack is already in this tree), #869 (give a put the call's pad).

## What is not on the server

The server is still on `2b7e415`, from the deploy that finished at 09:06 Madrid (13:36 IST).

That commit has the #794 tree, the untouched #676 pad, the #816 exits, today's index open, the cash-candle hold, the 09:25 macro, the fresh-base reentry, and paper. It does not have #872.

#872 was merged to `main` at 09:50 Madrid (14:20 IST). The EC2 deploy for `df294b91` was cancelled (`40659705012`), so the restart memory and the single trader pass never reached the machine. The public status endpoint still reports `2b7e415`.

Until that commit is deployed, a restart still drops `pnlPoints`, `bestPnlPoints`, and `maxLtp` on today's closed trades, and a chain rebuild can still run a second trader pass beside the live scan.
