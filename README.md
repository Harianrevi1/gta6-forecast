# GTA VI launch-day Twitch forecast

[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Harianrevi1/gta6-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Harianrevi1/gta6-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Forecasts, hour by hour, how many people watch Grand Theft Auto VI live on
Twitch over the 24 UTC hours of its release day, 19 November 2026 — from
everything recorded up to the end of the day's first hour, that hour's count
included. For each of hours 2 to 24 it writes five quantiles (5%, 25%, 50%,
75%, 95%) of that hour's concurrent viewer count.

Entry for the [make.fun bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
"Forecast GTA VI's launch-day Twitch viewers hour by hour" ($250 USDC).

## How it works

One anchor, one shape pool, no model, no network — Python 3.13 standard
library only, fully deterministic.

1. **Anchor.** The case's own hour-1 print `p` sets the scale.
2. **Shape pool.** Every comparable past launch whose release day (UTC) has
   all 24 hourly viewer counts contributes its launch-day curve, expressed
   as log-ratios to its own hour 1.
3. **Similarity by scale.** Only launches whose hour-1 size is close to `p`
   in log space (within 1.75, widened to 2.5 and then to all if fewer than 6
   remain) enter the pool. Launch-day shape depends strongly on scale: tiny
   hour-1 counts belong to games that explode later (100–2000x), while big
   launches ramp about 2–3x to a late-day peak. Mixing them wrecks the
   forecast.
4. **Empirical quantiles.** Per hour, the 5/25/50/75/95 percentiles of the
   pool's log-ratios (linear interpolation). Empirical quantiles capture the
   right skew of launch-day ramps better than a symmetric normal spread.
5. **Smoothing.** A 3-hour centred moving average of the log-quantiles,
   because a real audience curve is smooth hour to hour and per-hour
   empirical quantiles from ~20 launches are noisy.
6. **Fallback.** If no comparable is usable at all, the forecast falls back
   to a flat median with a widening spread (the house baseline's shape).

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `<id>.in` in the input directory and writes `<id>.out` per case:
`{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}` for hours
2 to 24. Runs in ~0.05 s per case, far under the 8 s cap; two runs write
byte-identical output.

## Validation (leave-one-out on the comparables)

With no practice answers shipped in the kit, the honest check is
leave-one-out over the 38 comparable launches: predict each launch's
release day from its own hour-1 print using the other 37 as the shape
pool, and score with the contest's pinball loss on the log scale.

On the launches that resemble the target — big launches with hour-1 counts
of 10,000 or more (28 of 37) — this forecaster scores **0.2714** against
the house baseline's **0.3508**, about 23% better, with 90% coverage of
0.828 (honest coverage is ~0.9). On console-only big launches (7 of them)
it scores 0.2042 against the baseline's 0.2828.

Two things that did *not* help, and were left out: restricting the pool to
console-only launches (the pool gets too small and the median gets noisy),
and using the pre-release hype ratio (hour 1 over the pre-week median) as
a shape conditioner (it does not predict the peak ratio).

## Layout

- `main.py` — the whole forecaster (the only entrypoint).
- `LICENSE` — MIT.
