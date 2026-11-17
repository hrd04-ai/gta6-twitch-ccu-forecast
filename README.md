# gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/hrd04-ai/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/hrd04-ai/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts GTA VI's launch-day Twitch viewers hour by hour as five quantiles, from the hour-1 print, with a scale-conditioned ensemble of past big launches.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=snhzbfb2&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>

## How it works

See the docstring at the top of `main.py`. In short: the shape of a big
launch's release day depends on how big it already is at the first print
(the log peak-to-hour-0 ratio correlates about -0.94 with log hour-0 viewers
across the comparables), so the forecast conditions on the hour-1 print and
works in log-ratios to it. Two scale-conditioned components are averaged in
log space: the 15 comparables nearest in log hour-0 (Normal quantiles from
their per-hour log-ratios) and a per-hour OLS trend of log-ratio on log
hour-0 (fit on comparables with hour-0 >= 10,000, so it extrapolates
smoothly when the hour-1 print exceeds every comparable). Spreads are
shrunk by 0.65 and the afternoon/evening hours get a small +0.05 log lift
for the Americas unlocking after hour 1.

## Validation (local, against the four practice cases)

Mean pinball loss on the log scale: **0.188** vs the house starter
(persistence) baseline **0.387**. Leave-one-out on the comparables:
0.120 for the six biggest launches (hour-0 >= 300k), 0.26 for mid-size
(100k-300k). Runtime ~0.2s per case, deterministic (two runs byte-identical),
standard library only, no network.

Reads every `<id>.in` under the input dir, writes `<id>.out` under the
output dir: `{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}`.
