# Paper alerts and daily brief

The replay requires no account. The live paper watch and daily brief are
optional and require data credentials; neither places orders. See
[setup](market-data.md). Run commands from the checkout with the virtual
environment activated.

## Paper alerts

```sh
autopsy alerts test-notify --notify console
# On macOS, add mac to --notify to test desktop notifications.
autopsy alerts replay --days 60 --out out/alerts.html            # invented prices
# After setting up the watchlist and Upstox token (see below):
autopsy alerts live --symbols ~/oracle-autopsy-watchlist.txt --notify console
autopsy alerts scorecard --out out/scorecard.html                # after the close
```

`live` polls Upstox's intraday candles 10 seconds after every five-minute
boundary until 15:16 IST, using the Analytics Token at
`~/.config/oracle-autopsy/upstox_analytics_token`
(mode 600); see the [market data guide](market-data.md). From the checkout, copy
`deploy/watchlist.example.txt` to `~/oracle-autopsy-watchlist.txt`, check each
instrument key against Upstox's instrument file, and keep it outside the repo.
Add `mac` (on macOS) or `telegram` to the comma-separated `--notify` list for
additional notification channels. Telegram reads
`~/.config/oracle-autopsy/telegram.json` (mode 600) with `bot_token` and
`chat_id`; messages go to that one chat. `deploy/launchd.plist.template` starts
the watch at 09:10 on weekdays under `caffeinate`. The scorecard reports
CAN'T TELL until 60 sessions and 100 trades.

## Daily brief and news

```sh
autopsy brief --notify console    # market strip + up to 3 Economic Times headlines
autopsy news poll                 # archive new ET market headlines (run hourly)
```

The brief uses read-only Kite quotes (with the credentials and manual login
in the [market data guide](market-data.md)): Nifty 50 and its 200-day regime,
India VIX, NIFTY 100 breadth and movers, up to three headlines, and the strategy status. If
the day's Kite login is missing it sends a reminder instead. Telegram needs
`~/.config/oracle-autopsy/telegram.json` (mode 600) with `bot_token` and
`chat_id`. Headlines are context only: they are archived with first-seen times
so they can become a pre-registered factor after a year, never used in
hindsight. See the [dated research notes](research/sources/2026-11-06-factors-and-news.md)
for the feed's personal-storage constraints. To schedule on a
Mac, fill `__REPO__` and `__HOME__` in `deploy/com.oracleautopsy.brief.plist.example`
and `deploy/com.oracleautopsy.news.plist.example`, copy them to
`~/Library/LaunchAgents/` without `.example`, and `launchctl load` each.
