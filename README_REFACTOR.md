# Fortnite Shop Bot — Refactor v2

Modular rewrite of the original `main.py` (70KB monolith) into clean packages while preserving the exact output image (10×10 grid, 512×625 cards, JPEG q=95, footer `@FortniteDailyStoreBot`).

## What changed

### Structure
```
bot/
├── __main__.py          entry point
├── config.py            settings + validation
├── core/
│   ├── instance.py      bot, dispatcher, storage
│   ├── middleware.py    AccessMiddleware, LoggingMiddleware
│   └── states.py        all FSMs
├── handlers/
│   ├── user.py          /start, menu
│   ├── admin_panel.py   /admin entrypoint
│   ├── admin_users.py
│   ├── admin_channels.py
│   ├── admin_broadcast.py
│   ├── admin_settings.py
│   ├── admin_filters.py NEW: ignore-by-type/rarity/price
│   ├── admin_logs.py
│   └── admin_generation.py
├── keyboards/
│   ├── main.py
│   └── admin.py
├── services/
│   ├── shop_api.py      Fortnite API client + retries
│   ├── shop_generator.py  bridges API -> image_builder -> grid
│   ├── image_builder.py cards (EXACT same output as before)
│   ├── shop_checker.py  smart hash compare
│   ├── poster.py        post to channels
│   └── backup.py        scheduled DB backup
├── db/
│   ├── connection.py
│   ├── users.py
│   ├── shop.py
│   ├── channels.py
│   ├── stats.py
│   ├── config.py
│   ├── filters.py       NEW: ignore filters table
│   └── logs.py
└── scheduler.py
```

### Fixed bugs (Fortnite API)
- Items WITHOUT `brItems` (tracks, cars, instruments, bundle-only) were silently dropped — now processed
- Bundles without `brItems` no longer crash on rarity lookup
- Added retries (3x exponential backoff) on icon download
- Dedup by (item_id, finalPrice) so the same skin in multiple offers = one card
- Jam Tracks hard-filter moved to user-configurable ignore filters
- Detailed counters logged: received, processed, skipped (with reason)
- Raw shop dump saved to `last_shop_dump.json` for debugging
- Fallback chain for icon URL: OfferImage → newDisplayAsset.background → brItems[0].images.featured → icon

### New admin features
- **Filters menu** — ignore by type (outfit/backpack/wrap/emote/music/car/track/instrument/bundle/spray/etc), rarity, price range, new-only toggle
- Test API without generation (diagnostic)
- API health monitoring + alert on 3+ consecutive failures
- Stats: generations/users/channels/API errors (7d window)
- Customizable footer text + date format
- Manage main + admin banners from bot (no restart)
- Custom cron schedule
- User CSV export
- User search by id/username
- Logs: pagination, filter by action type

### Preserved 1:1
- Card size 512×625
- Grid 10×10 (100 items per image)
- Footer text/font/color (#1c1c1c, 60pt)
- JPEG quality 95
- Rarity background overlay rules
- All existing FSM flows and admin sections

## Migration

1. `pip install -r requirements.txt` (no new deps)
2. Copy `users.db`, `logs.db`, `images/`, `fonts/` from old layout — they stay in repo root
3. `settings.py` stays as is, with `API_TOKEN` populated
4. Run: `python -m bot`

## Run

```bash
python -m bot
```

Or legacy mode (old main.py still in repo as `legacy_main.py`):
```bash
python legacy_main.py
```
