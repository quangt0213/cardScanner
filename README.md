# Raspberry Pi Trading Card Scanner Backend

This project is a Raspberry Pi 4 backend for identifying trading cards from JPEG images posted by an ESP32-CAM over WiFi. It supports Pokemon and One Piece cards through a provider abstraction, stores successful matches locally in `carddata.db`, and shows the latest scan state on a Flask-rendered UI suitable for a Freenove Raspberry Pi touchscreen.

## How The System Works

1. The ESP32-CAM sends a JPEG to `POST /scan`.
2. Flask validates that the upload is a JPEG and saves it under `data/scans/` with a UTC timestamp.
3. A lightweight internal scan worker runs the heavy pipeline.
4. OpenCV preprocesses the image and tries ORB feature matching against cards already cached in `carddata.db`.
5. If the local match confidence is at least `LOCAL_MATCH_THRESHOLD`, the result returns immediately and OCR/API lookup is skipped.
6. If local matching is weak, EasyOCR extracts card text from the image.
7. OCR text is cleaned into search queries and sent to all configured providers: Pokemon, One Piece, and optional mock.
8. The top 20 normalized candidates are collected, candidate images are cached under `data/cache/candidate_images/`, and OpenCV ranks them with the same ORB matcher.
9. If the best remote candidate reaches `REMOTE_MATCH_THRESHOLD`, it is saved to SQLite with cached image and descriptors for faster future local matching.
10. Every scan attempt is written to `scan_history`.
11. The display adapter updates `data/cache/display_state.json`, and `/display` renders it for the Freenove touchscreen.
12. `POST /scan` returns JSON with match status, name, game, set, price, confidence, source, OCR text, image path, and DB id.

## 64GB microSD Storage Strategy

The scanner uses SQLite for permanent metadata and file indexes, but not for full-size card image BLOBs. Full images stay on disk where they can be deduplicated, pruned, replaced, or rebuilt without bloating `carddata.db`. SQLite stores paths, hashes, provider IDs, latest prices, compact price history, scan history, and cache records.

Storage tiers:

| Tier | Location | Purpose | Retention |
| --- | --- | --- | --- |
| Tier 1 | `carddata.db` | Permanent card metadata, provider IDs, hashes, latest price, scan history, cache index | Long-lived |
| Tier 2 | `data/descriptors/` | ORB descriptors for fast local matching | Kept longer than images, rebuildable |
| Tier 3 | `data/cache/card_images/` | Full-size cached images for known/recent/frequent cards | LRU capped |
| Tier 4 | `data/cache/candidate_temp/` | Temporary remote API candidate downloads | TTL plus size cap |

Recommended conservative budget for a 64GB card:

| Area | Default cap | Why |
| --- | ---: | --- |
| Free space reserve | 20GB | Leaves room for OS updates, package cache, swap, and SD wear leveling |
| `data/scans/` originals | 1GB | Keeps recent evidence without archiving every ESP32-CAM upload forever |
| `data/cache/card_images/` | 2GB | Enough for thousands of card images while staying bounded |
| `data/cache/candidate_temp/` | 512MB | Remote candidates are short-lived and easy to redownload |
| `data/descriptors/` | 256MB | ORB descriptors are small and valuable for fast repeat matches |
| `logs/` | 128MB | Rotating logs only; avoid verbose disk logging |
| `carddata.db` warning | 256MB | Metadata should remain compact; investigate if it grows past this |

These defaults keep scanner-owned storage near 4GB while leaving a healthy amount of free space on a 64GB microSD card.

## Eviction And Retention

Eviction order:

1. Expired Tier 4 candidate temp files are deleted first because they are transient API downloads.
2. Old unpinned uploaded scan originals are pruned after `SCAN_ORIGINAL_TTL_DAYS`.
3. Full-size Tier 3 card images are evicted by LRU when `IMAGE_CACHE_MAX_BYTES` is exceeded.
4. Debug scan copies are kept longer than originals but are lower quality and also TTL managed.
5. Tier 2 descriptors are kept longest because they are small and speed up local matching. They are still rebuildable from cached or redownloaded card images.

Default retention:

- Original uploaded scans: 14 days.
- Lower-resolution debug scan copies: 45 days.
- Candidate temp downloads: 72 hours.
- API query cache: 24 hours.
- Price refresh: no more than once every 24 hours by default.

Permanent data:

- Normalized card metadata.
- Provider source and API ID.
- Latest known price and compact price history.
- Scan history metadata.
- File hashes and cache indexes.

Rebuildable data:

- ORB descriptor files.
- Full-size cached card images.
- Temporary candidate downloads.
- Debug scan copies.
- Uploaded scan JPEGs after the retention window.

If cache folders are deleted but `carddata.db` remains, startup maintenance removes stale cache records, keeps card metadata, and lazily rebuilds descriptors when a source image is available. If source images are gone, the next OCR/API match can redownload and recache the card art.

## SD-Card-Friendly Writes

The backend avoids making the microSD card a dumping ground:

- Repeated uploads are hash-deduplicated before a new scan file is written.
- Candidate downloads are short-lived and cleaned by TTL.
- Confirmed remote art is copied once into the reusable image cache.
- Descriptor files are generated lazily and reused for local matching.
- SQLite stores compact metadata, not large image BLOBs.
- Logs use a rotating file handler; keep `DEBUG=false` for normal use.
- Transient files that do not need reboot survival can be pointed at a RAM-backed path by setting `CANDIDATE_TEMP_DIR=/tmp/card-scanner-candidates`.

Database writes are kept practical and small: one scan history row per scan, one card upsert for confident remote matches, and price history only when the observed price changes. For a single-scanner Pi workload, this is simpler and safer than introducing a heavier batching service.

## Why Flask Plus A Small Worker

Flask remains the API and UI layer because it is simple and reliable on a Raspberry Pi 4. OCR, remote API calls, image downloads, and matching many candidates can take seconds and use noticeable CPU. Instead of adding Redis, Celery, or another service, this project uses `SimpleJobService`, an in-process `ThreadPoolExecutor`.

The worker/service:

- `scan-worker`: runs the full image-processing pipeline after Flask has saved the JPEG.
- Purpose: keep heavy OCR, provider fetches, candidate downloads, and OpenCV matching out of the route handler.
- Why it exists: a Pi 4 can become sluggish if several scans run at once, so the default `SCAN_WORKERS=1` serializes scan work.
- Tasks that remain in Flask: upload validation, file saving, health checks, job status, history endpoint, and touchscreen UI rendering.

By default, `POST /scan` waits for the worker result so the ESP32-CAM receives the final JSON response. Add `?async=1` or set `BLOCKING_SCAN_RESPONSE=false` to return a queued `job_id` and poll `/jobs/<job_id>`.

## Project Structure

```text
app.py
config.py
requirements.txt
README.md
.env.example
database/
  init_db.py
  schema.sql
  repository.py
  seed_sample_cards.py
services/
  image_matcher.py
  ocr_service.py
  card_lookup_service.py
  candidate_ranker.py
  scan_pipeline.py
  display_service.py
  cache_service.py
  job_service.py
  cache_policy.py
  descriptor_store.py
  storage_manager.py
  maintenance_service.py
providers/
  base_provider.py
  pokemon_provider.py
  onepiece_provider.py
  mock_provider.py
routes/
  scan_routes.py
  ui_routes.py
utils/
  image_utils.py
  text_utils.py
  logger.py
templates/
  display.html
  result.html
static/
  styles.css
data/
  scans/
  cache/
    card_images/
    candidate_temp/
    scan_debug/
  descriptors/
tests/
  test_image_matcher.py
  test_text_utils.py
  test_candidate_ranker.py
  test_pipeline.py
```

## Raspberry Pi 4 Setup

Use Python 3.11 or newer. On Raspberry Pi OS, install system packages first:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip libgl1 libglib2.0-0
```

Then set up the project:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python database/init_db.py
python database/seed_sample_cards.py
python app.py
```

The API will listen on `http://0.0.0.0:5000` by default.

## Configuration

Copy `.env.example` to `.env` and adjust values as needed.

Important settings:

- `LOCAL_MATCH_THRESHOLD`: confidence needed to trust the local SQLite/descriptor match.
- `REMOTE_MATCH_THRESHOLD`: confidence needed to trust a remote provider candidate.
- `SCAN_WORKERS`: default `1`, recommended for Raspberry Pi 4.
- `SCANS_MAX_BYTES`: default `1GB`.
- `IMAGE_CACHE_MAX_BYTES`: default `2GB`.
- `CANDIDATE_TEMP_MAX_BYTES`: default `512MB`.
- `DESCRIPTORS_MAX_BYTES`: default `256MB`.
- `MIN_FREE_SPACE_BYTES`: default `20GB`.
- `SCAN_ORIGINAL_TTL_DAYS`: default `14`.
- `CANDIDATE_TEMP_TTL_HOURS`: default `72`.
- `ENABLE_MOCK_PROVIDER`: keep `true` for offline development.
- `POKEMON_TCG_API_KEY`: optional for Pokemon TCG API.
- `ONEPIECE_API_BASE_URL` and `ONEPIECE_API_KEY`: configurable because One Piece APIs vary by provider.
- `OCR_ENABLED`: set `false` to skip EasyOCR during quick development.

If no remote API credentials are supplied, the project still runs with `MockProvider`.

## ESP32-CAM Upload

The scanner accepts either a multipart file field named `image` or a raw `image/jpeg` request body.

Raw JPEG:

```cpp
HTTPClient http;
http.begin("http://RASPBERRY_PI_IP:5000/scan");
http.addHeader("Content-Type", "image/jpeg");
int code = http.POST(jpegBuffer, jpegLength);
String response = http.getString();
http.end();
```

Multipart uploads also work if your ESP32-CAM firmware sends `form-data` with the field name `image`.

## Test With Curl

Raw JPEG body:

```bash
curl -X POST \
  -H "Content-Type: image/jpeg" \
  --data-binary @sample-card.jpg \
  http://RASPBERRY_PI_IP:5000/scan
```

Multipart:

```bash
curl -X POST \
  -F "image=@sample-card.jpg;type=image/jpeg" \
  http://RASPBERRY_PI_IP:5000/scan
```

Async mode:

```bash
curl -X POST \
  -H "Content-Type: image/jpeg" \
  --data-binary @sample-card.jpg \
  "http://RASPBERRY_PI_IP:5000/scan?async=1"

curl http://RASPBERRY_PI_IP:5000/jobs/JOB_ID
```

## Freenove Touchscreen Display

The Freenove monitor is treated as the Pi display. Start the Flask server, then open Chromium on the Pi:

```bash
chromium-browser --kiosk http://localhost:5000/display
```

The `/display` page auto-refreshes and shows:

- card name
- Pokemon or One Piece
- set name
- price
- confidence
- match source, such as `local_db` or `remote_api`

The backend updates the display after success, low-confidence results, OCR failures, and pipeline errors.

## API Endpoints

### `GET /health`

Returns:

```json
{
  "ok": true,
  "service": "raspi-card-scanner"
}
```

### `POST /scan`

Returns a final result by default:

```json
{
  "matched": true,
  "card_name": "Pikachu",
  "game": "pokemon",
  "set_name": "Base Set",
  "price": 12.34,
  "currency": "USD",
  "confidence": 0.67,
  "source": "local_db",
  "ocr_text": "",
  "image_path": "data/scans/scan_20260502T120000000000Z.jpg",
  "db_id": 123
}
```

### `GET /jobs/<job_id>`

Returns queued/running/finished/failed state for async scans.

### `GET /history`

Returns recent scan history rows.

### `GET /display`

Touchscreen UI for the latest scan state.

## Provider Layer

All providers return the same `CandidateCard` schema:

- `game`
- `card_name`
- `set_name`
- `collector_number`
- `rarity`
- `image_url`
- `price`
- `currency`
- `source`
- `api_id`

Included providers:

- `PokemonProvider`: uses the Pokemon TCG API.
- `OnePieceProvider`: uses a configurable APITCG-compatible endpoint.
- `MockProvider`: works offline and powers tests/development.

## Database

SQLite database file: `carddata.db`.

Tables:

- `cards`: normalized card records and cached descriptor paths.
- `card_images`: image references for known cards.
- `scan_history`: every attempt, including failures and confidence.
- `api_cache`: provider query cache to reduce network calls.
- `storage_files`: tier, path, hash, size, expiry, LRU access time, and pinning metadata.
- `price_history`: compact price observations only when a price changes.

Schema choices:

- Full-size images are not stored as SQLite BLOBs.
- ORB descriptors are separate `.npz` files, indexed by path in SQLite.
- Provider-specific raw metadata is stored in `metadata_json` for expandability.
- New games reuse the same `game`, `api_source`, `api_id`, `storage_files`, and `metadata_json` model.

Price strategy:

- `cards.price` and `cards.currency` hold the latest known value for display.
- `price_history` stores compact observations only when the value changes.
- Provider/API prices should be refreshed during OCR/API lookup or by a future scheduled refresh, not on every local DB match.
- `PRICE_REFRESH_MIN_HOURS=24` is a good default to avoid noisy writes and excessive API calls.

## Startup Maintenance

`MaintenanceService` runs at startup and performs a small bounded cleanup:

- validates all storage directories;
- removes storage index rows for missing files;
- prunes expired candidate temp files;
- prunes old uploaded scan originals;
- enforces LRU size caps;
- rebuilds a small number of missing descriptors from available local images.

The scan pipeline interacts with storage like this:

1. `/scan` saves the JPEG through `StorageManager`, which hashes and deduplicates repeated uploads.
2. Local matching loads existing descriptors from `DescriptorStore`.
3. OCR/API candidates are downloaded into `candidate_temp`.
4. The best confident remote match is promoted into `card_images`.
5. ORB descriptors are generated lazily and stored in `data/descriptors/`.
6. SQLite records card metadata, file paths, hashes, latest price, scan history, and cache index rows.

## Testing

Run:

```bash
pytest
```

The tests use temporary files and the mock provider. They do not require network access or EasyOCR.
# Raspberry Pi Trading Card Scanner Backend

This project is a Raspberry Pi 4 backend for identifying trading cards from JPEG images posted by an ESP32-CAM over WiFi. It supports Pokemon and One Piece cards through a provider abstraction, stores successful matches locally in `carddata.db`, and shows the latest scan state on a Flask-rendered UI suitable for a Freenove Raspberry Pi touchscreen.

## How The System Works

1. The ESP32-CAM sends a JPEG to `POST /scan`.
2. Flask validates that the upload is a JPEG and saves it under `data/scans/` with a UTC timestamp.
3. A lightweight internal scan worker runs the heavy pipeline.
4. OpenCV preprocesses the image and tries ORB feature matching against cards already cached in `carddata.db`.
5. If the local match confidence is at least `LOCAL_MATCH_THRESHOLD`, the result returns immediately and OCR/API lookup is skipped.
6. If local matching is weak, EasyOCR extracts card text from the image.
7. OCR text is cleaned into search queries and sent to all configured providers: Pokemon, One Piece, and optional mock.
8. The top 20 normalized candidates are collected, candidate images are cached under `data/cache/candidate_images/`, and OpenCV ranks them with the same ORB matcher.
9. If the best remote candidate reaches `REMOTE_MATCH_THRESHOLD`, it is saved to SQLite with cached image and descriptors for faster future local matching.
10. Every scan attempt is written to `scan_history`.
11. The display adapter updates `data/cache/display_state.json`, and `/display` renders it for the Freenove touchscreen.
12. `POST /scan` returns JSON with match status, name, game, set, price, confidence, source, OCR text, image path, and DB id.

## 64GB microSD Storage Strategy

The scanner uses SQLite for permanent metadata and file indexes, but not for full-size card image BLOBs. Full images stay on disk where they can be deduplicated, pruned, replaced, or rebuilt without bloating `carddata.db`. SQLite stores paths, hashes, provider IDs, latest prices, compact price history, scan history, and cache records.

Storage tiers:

| Tier | Location | Purpose | Retention |
| --- | --- | --- | --- |
| Tier 1 | `carddata.db` | Permanent card metadata, provider IDs, hashes, latest price, scan history, cache index | Long-lived |
| Tier 2 | `data/descriptors/` | ORB descriptors for fast local matching | Kept longer than images, rebuildable |
| Tier 3 | `data/cache/card_images/` | Full-size cached images for known/recent/frequent cards | LRU capped |
| Tier 4 | `data/cache/candidate_temp/` | Temporary remote API candidate downloads | TTL plus size cap |

Recommended conservative budget for a 64GB card:

| Area | Default cap | Why |
| --- | ---: | --- |
| Free space reserve | 20GB | Leaves room for OS updates, package cache, swap, and SD wear leveling |
| `data/scans/` originals | 1GB | Keeps recent evidence without archiving every ESP32-CAM upload forever |
| `data/cache/card_images/` | 2GB | Enough for thousands of card images while staying bounded |
| `data/cache/candidate_temp/` | 512MB | Remote candidates are short-lived and easy to redownload |
| `data/descriptors/` | 256MB | ORB descriptors are small and valuable for fast repeat matches |
| `logs/` | 128MB | Rotating logs only; avoid verbose disk logging |
| `carddata.db` warning | 256MB | Metadata should remain compact; investigate if it grows past this |

These defaults keep scanner-owned storage near 4GB while leaving a healthy amount of free space on a 64GB microSD card.

## Eviction And Retention

Eviction order:

1. Expired Tier 4 candidate temp files are deleted first because they are transient API downloads.
2. Old unpinned uploaded scan originals are pruned after `SCAN_ORIGINAL_TTL_DAYS`.
3. Full-size Tier 3 card images are evicted by LRU when `IMAGE_CACHE_MAX_BYTES` is exceeded.
4. Debug scan copies are kept longer than originals but are lower quality and also TTL managed.
5. Tier 2 descriptors are kept longest because they are small and speed up local matching. They are still rebuildable from cached or redownloaded card images.

Default retention:

- Original uploaded scans: 14 days.
- Lower-resolution debug scan copies: 45 days.
- Candidate temp downloads: 72 hours.
- API query cache: 24 hours.
- Price refresh: no more than once every 24 hours by default.

Permanent data:

- Normalized card metadata.
- Provider source and API ID.
- Latest known price and compact price history.
- Scan history metadata.
- File hashes and cache indexes.

Rebuildable data:

- ORB descriptor files.
- Full-size cached card images.
- Temporary candidate downloads.
- Debug scan copies.
- Uploaded scan JPEGs after the retention window.

If cache folders are deleted but `carddata.db` remains, startup maintenance removes stale cache records, keeps card metadata, and lazily rebuilds descriptors when a source image is available. If source images are gone, the next OCR/API match can redownload and recache the card art.

## SD-Card-Friendly Writes

The backend avoids making the microSD card a dumping ground:

- Repeated uploads are hash-deduplicated before a new scan file is written.
- Candidate downloads are short-lived and cleaned by TTL.
- Confirmed remote art is copied once into the reusable image cache.
- Descriptor files are generated lazily and reused for local matching.
- SQLite stores compact metadata, not large image BLOBs.
- Logs use a rotating file handler; keep `DEBUG=false` for normal use.
- Transient files that do not need reboot survival can be pointed at a RAM-backed path by setting `CANDIDATE_TEMP_DIR=/tmp/card-scanner-candidates`.

Database writes are kept practical and small: one scan history row per scan, one card upsert for confident remote matches, and price history only when the observed price changes. For a single-scanner Pi workload, this is simpler and safer than introducing a heavier batching service.

## Why Flask Plus A Small Worker

Flask remains the API and UI layer because it is simple and reliable on a Raspberry Pi 4. OCR, remote API calls, image downloads, and matching many candidates can take seconds and use noticeable CPU. Instead of adding Redis, Celery, or another service, this project uses `SimpleJobService`, an in-process `ThreadPoolExecutor`.

The worker/service:

- `scan-worker`: runs the full image-processing pipeline after Flask has saved the JPEG.
- Purpose: keep heavy OCR, provider fetches, candidate downloads, and OpenCV matching out of the route handler.
- Why it exists: a Pi 4 can become sluggish if several scans run at once, so the default `SCAN_WORKERS=1` serializes scan work.
- Tasks that remain in Flask: upload validation, file saving, health checks, job status, history endpoint, and touchscreen UI rendering.

By default, `POST /scan` waits for the worker result so the ESP32-CAM receives the final JSON response. Add `?async=1` or set `BLOCKING_SCAN_RESPONSE=false` to return a queued `job_id` and poll `/jobs/<job_id>`.

## Project Structure

```text
app.py
config.py
requirements.txt
README.md
.env.example
database/
  init_db.py
  schema.sql
  repository.py
  seed_sample_cards.py
services/
  image_matcher.py
  ocr_service.py
  card_lookup_service.py
  candidate_ranker.py
  scan_pipeline.py
  display_service.py
  cache_service.py
  job_service.py
  cache_policy.py
  descriptor_store.py
  storage_manager.py
  maintenance_service.py
providers/
  base_provider.py
  pokemon_provider.py
  onepiece_provider.py
  mock_provider.py
routes/
  scan_routes.py
  ui_routes.py
utils/
  image_utils.py
  text_utils.py
  logger.py
templates/
  display.html
  result.html
static/
  styles.css
data/
  scans/
  cache/
    card_images/
    candidate_temp/
    scan_debug/
  descriptors/
tests/
  test_image_matcher.py
  test_text_utils.py
  test_candidate_ranker.py
  test_pipeline.py
```

## Raspberry Pi 4 Setup

Use Python 3.11 or newer. On Raspberry Pi OS, install system packages first:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip libgl1 libglib2.0-0
```

Then set up the project:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python database/init_db.py
python database/seed_sample_cards.py
python app.py
```

The API will listen on `http://0.0.0.0:5000` by default.

## Configuration

Copy `.env.example` to `.env` and adjust values as needed.

Important settings:

- `LOCAL_MATCH_THRESHOLD`: confidence needed to trust the local SQLite/descriptor match.
- `REMOTE_MATCH_THRESHOLD`: confidence needed to trust a remote provider candidate.
- `SCAN_WORKERS`: default `1`, recommended for Raspberry Pi 4.
- `SCANS_MAX_BYTES`: default `1GB`.
- `IMAGE_CACHE_MAX_BYTES`: default `2GB`.
- `CANDIDATE_TEMP_MAX_BYTES`: default `512MB`.
- `DESCRIPTORS_MAX_BYTES`: default `256MB`.
- `MIN_FREE_SPACE_BYTES`: default `20GB`.
- `SCAN_ORIGINAL_TTL_DAYS`: default `14`.
- `CANDIDATE_TEMP_TTL_HOURS`: default `72`.
- `ENABLE_MOCK_PROVIDER`: keep `true` for offline development.
- `POKEMON_TCG_API_KEY`: optional for Pokemon TCG API.
- `ONEPIECE_API_BASE_URL` and `ONEPIECE_API_KEY`: configurable because One Piece APIs vary by provider.
- `OCR_ENABLED`: set `false` to skip EasyOCR during quick development.

If no remote API credentials are supplied, the project still runs with `MockProvider`.

## ESP32-CAM Upload

The scanner accepts either a multipart file field named `image` or a raw `image/jpeg` request body.

Raw JPEG:

```cpp
HTTPClient http;
http.begin("http://RASPBERRY_PI_IP:5000/scan");
http.addHeader("Content-Type", "image/jpeg");
int code = http.POST(jpegBuffer, jpegLength);
String response = http.getString();
http.end();
```

Multipart uploads also work if your ESP32-CAM firmware sends `form-data` with the field name `image`.

## Test With Curl

Raw JPEG body:

```bash
curl -X POST \
  -H "Content-Type: image/jpeg" \
  --data-binary @sample-card.jpg \
  http://RASPBERRY_PI_IP:5000/scan
```

Multipart:

```bash
curl -X POST \
  -F "image=@sample-card.jpg;type=image/jpeg" \
  http://RASPBERRY_PI_IP:5000/scan
```

Async mode:

```bash
curl -X POST \
  -H "Content-Type: image/jpeg" \
  --data-binary @sample-card.jpg \
  "http://RASPBERRY_PI_IP:5000/scan?async=1"

curl http://RASPBERRY_PI_IP:5000/jobs/JOB_ID
```

## Freenove Touchscreen Display

The Freenove monitor is treated as the Pi display. Start the Flask server, then open Chromium on the Pi:

```bash
chromium-browser --kiosk http://localhost:5000/display
```

The `/display` page auto-refreshes and shows:

- card name
- Pokemon or One Piece
- set name
- price
- confidence
- match source, such as `local_db` or `remote_api`

The backend updates the display after success, low-confidence results, OCR failures, and pipeline errors.

## API Endpoints

### `GET /health`

Returns:

```json
{
  "ok": true,
  "service": "raspi-card-scanner"
}
```

### `POST /scan`

Returns a final result by default:

```json
{
  "matched": true,
  "card_name": "Pikachu",
  "game": "pokemon",
  "set_name": "Base Set",
  "price": 12.34,
  "currency": "USD",
  "confidence": 0.67,
  "source": "local_db",
  "ocr_text": "",
  "image_path": "data/scans/scan_20260502T120000000000Z.jpg",
  "db_id": 123
}
```

### `GET /jobs/<job_id>`

Returns queued/running/finished/failed state for async scans.

### `GET /history`

Returns recent scan history rows.

### `GET /display`

Touchscreen UI for the latest scan state.

## Provider Layer

All providers return the same `CandidateCard` schema:

- `game`
- `card_name`
- `set_name`
- `collector_number`
- `rarity`
- `image_url`
- `price`
- `currency`
- `source`
- `api_id`

Included providers:

- `PokemonProvider`: uses the Pokemon TCG API.
- `OnePieceProvider`: uses a configurable APITCG-compatible endpoint.
- `MockProvider`: works offline and powers tests/development.

## Database

SQLite database file: `carddata.db`.

Tables:

- `cards`: normalized card records and cached descriptor paths.
- `card_images`: image references for known cards.
- `scan_history`: every attempt, including failures and confidence.
- `api_cache`: provider query cache to reduce network calls.
- `storage_files`: tier, path, hash, size, expiry, LRU access time, and pinning metadata.
- `price_history`: compact price observations only when a price changes.

Schema choices:

- Full-size images are not stored as SQLite BLOBs.
- ORB descriptors are separate `.npz` files, indexed by path in SQLite.
- Provider-specific raw metadata is stored in `metadata_json` for expandability.
- New games reuse the same `game`, `api_source`, `api_id`, `storage_files`, and `metadata_json` model.

Price strategy:

- `cards.price` and `cards.currency` hold the latest known value for display.
- `price_history` stores compact observations only when the value changes.
- Provider/API prices should be refreshed during OCR/API lookup or by a future scheduled refresh, not on every local DB match.
- `PRICE_REFRESH_MIN_HOURS=24` is a good default to avoid noisy writes and excessive API calls.

## Startup Maintenance

`MaintenanceService` runs at startup and performs a small bounded cleanup:

- validates all storage directories;
- removes storage index rows for missing files;
- prunes expired candidate temp files;
- prunes old uploaded scan originals;
- enforces LRU size caps;
- rebuilds a small number of missing descriptors from available local images.

The scan pipeline interacts with storage like this:

1. `/scan` saves the JPEG through `StorageManager`, which hashes and deduplicates repeated uploads.
2. Local matching loads existing descriptors from `DescriptorStore`.
3. OCR/API candidates are downloaded into `candidate_temp`.
4. The best confident remote match is promoted into `card_images`.
5. ORB descriptors are generated lazily and stored in `data/descriptors/`.
6. SQLite records card metadata, file paths, hashes, latest price, scan history, and cache index rows.

## Testing

Run:

```bash
pytest
```

The tests use temporary files and the mock provider. They do not require network access or EasyOCR.
