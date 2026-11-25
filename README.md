# Trade Order Engine

A Python + FastAPI order engine providing strongly typed trading enums, option contract parsing, strict API validation, defense-in-depth access control, and a headerless append-only `.txt` OrderBook writer supporting **place**, **modify**, and **cancel** workflows.

## Features

- **Exact 9-Field Headerless `.txt` Format**:
  `UNIQ NO,CONTRACT,BUY/SELL,LOT,PRICE,ORDER_TYPE,ID,STG_ID,NOTE` (data rows only, no header line written).
- **Limit & Market Rules**:
  - **Limit order**: `PRICE > 0`, writes `ORDER_TYPE = "L"`.
  - **Market order**: `PRICE = 0`, **also writes `ORDER_TYPE = "L"`**.
  - **Modify**: writes `ORDER_TYPE = "M"`.
  - **Cancel**: writes `ORDER_TYPE = "C"`.
- **Strictly Internal `ID` (`client_id`)**: Configured server-side via `ORDER_CLIENT_ID` and injected internally into `.txt` rows — never accepted in public API requests and never exposed in API responses.
- **Validated Order Lifecycle API**:
  - **Place** single (`POST /orders`) or multi-leg atomic batches (`POST /orders/batch`)
  - **Modify** active orders by `uniq_no` (`PATCH /orders/{uniq_no}`)
  - **Cancel** active orders by `uniq_no` (`DELETE /orders/{uniq_no}`)
  - **Query** latest order state (`GET /orders/{uniq_no}`) or filter rows (`GET /orders`)
- **Defense-in-Depth Security**:
  - **Fail-closed API key authentication** (`X-API-Key` or `Authorization: Bearer <key>`) with constant-time verification and key rotation (`ORDER_API_KEYS`)
  - **Optional HMAC-SHA256 request signing** (`ORDER_HMAC_SECRET`) with clock-skew checks against tampering and replay attacks
  - **IP / CIDR allowlist** (`ORDER_ALLOWED_IPS`) with proxy-spoof-resistant `X-Forwarded-For` resolution
  - **Per-IP sliding-window rate limiter**, payload size cap (`413`), security response headers, audit logging, `0600` `.txt` file permissions, and `/docs` disabled by default
- **Safe `.txt` Persistence**: Exact `Decimal` pricing, `threading.Lock` + POSIX `fcntl.flock` concurrency safety, `flush` + `fsync`, and atomic read-validate-append transactions.

## Project Structure

```text
trade_order_engine/
├── .env.example
├── pyproject.toml
├── README.md
├── src/
│   └── trade_order_engine/
│       ├── __init__.py
│       ├── config.py                # Environment & security settings
│       ├── exceptions.py            # Domain exceptions (403 / 404 / 409 / 422)
│       ├── enums/
│       │   ├── book.py              # BookType, OrderBookColumn (9-col schema)
│       │   ├── instrument.py        # OptionType, InstrumentType, Underlying
│       │   └── order.py             # OrderSide, OrderType (L/M/C), PriceType (LIMIT/MARKET)
│       ├── models/
│       │   ├── contract.py          # Contract symbol parser
│       │   └── order.py             # OrderRecord (9-field OrderBook row)
│       ├── schemas/
│       │   └── order.py             # Pydantic v2 request/response DTOs
│       ├── security/
│       │   ├── __main__.py          # `python -m trade_order_engine.security` keygen
│       │   ├── auth.py              # Constant-time API key & HMAC-SHA256 helpers
│       │   ├── ip_filter.py         # IP/CIDR allowlist + safe proxy header handling
│       │   └── rate_limit.py        # Thread-safe sliding-window rate limiter
│       ├── storage/
│       │   └── orderbook_writer.py  # Thread/file-locked headerless .txt store (0600 perms)
│       ├── services/
│       │   └── order_service.py     # Place, modify, cancel & query orchestration
│       └── api/
│           ├── app.py               # FastAPI app factory, lifespan & security middleware
│           ├── dependencies.py      # Auth & HMAC FastAPI dependency
│           └── routes/
│               ├── health.py        # Minimal public GET /health
│               └── orders.py        # Protected /orders endpoints
└── tests/
    ├── test_enums.py
    ├── test_models.py
    ├── test_storage.py
    ├── test_api.py
    └── test_security.py
```

## Domain Enums Reference

| Enum | Values |
| :--- | :--- |
| `OrderSide` | `BUY = 1`, `SELL = 2` |
| `OrderType` | `PLACE = "L"` (Limit & Market), `MODIFY = "M"`, `CANCEL = "C"` |
| `PriceType` | `LIMIT` (`PRICE > 0`, `ORDER_TYPE = "L"`), `MARKET` (`PRICE = 0`, `ORDER_TYPE = "L"`) |
| `OptionType` | `CALL = "CE"` (`CE`), `PUT = "PE"` (`PE`) |
| `InstrumentType` | `OPTION = "OPT"`, `FUTURE = "FUT"`, `EQUITY = "EQ"` |
| `Underlying` | `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `SENSEX`, `BANKEX` |
| `BookType` | `ORDER_BOOK = "OrderBook"`, `TRADE_BOOK = "TradeBook"` |
| `OrderBookColumn` | `UNIQ NO`, `CONTRACT`, `BUY/SELL`, `LOT`, `PRICE`, `ORDER_TYPE`, `ID`, `STG_ID`, `NOTE` |

## OrderBook `.txt` Format (Headerless, 9 Fields)

Column order: `UNIQ NO,CONTRACT,BUY/SELL,LOT,PRICE,ORDER_TYPE,ID,STG_ID,NOTE` (no header line written; server injects internal `ORDER_CLIENT_ID` into column 7):

```text
# Place Market order (PRICE = 0, ORDER_TYPE = L)
676,NIFTY2690823850CE,2,5,0,L,<INTERNAL_ID>,763,275.55

# Place Limit order -> Modify -> Cancel
677,NIFTY2690823850CE,2,5,275.55,L,<INTERNAL_ID>,763,entry
677,NIFTY2690823850CE,2,10,276.25,M,<INTERNAL_ID>,763,entry
677,NIFTY2690823850CE,2,10,276.25,C,<INTERNAL_ID>,763,entry
```

## Quick Start & Hosting Security

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Generate Strong Secrets

```bash
python3 -m trade_order_engine.security
```

Copy `.env.example` to `.env` (never commit `.env`) and set `ORDER_CLIENT_ID` plus the generated secrets.

### 3. Configuration Reference

| Env Variable | Default | Purpose |
| :--- | :--- | :--- |
| `ORDERBOOK_FILE_PATH` | `data/OrderBook.txt` | Output `.txt` file path (`0600` permissions) |
| `ORDER_CLIENT_ID` | *(required)* | Internal `ID` injected into `.txt` rows (never exposed publicly) |
| `ORDER_AUTH_ENABLED` | `true` | Fail-closed auth guard (refuses to boot without a key) |
| `ORDER_API_KEY` | *(required)* | Secret key sent via `X-API-Key` or `Authorization: Bearer` |
| `ORDER_API_KEYS` | *(optional)* | Comma-separated keys for zero-downtime key rotation |
| `ORDER_HMAC_SECRET` | *(optional)* | Enables `X-Timestamp` + `X-Signature` HMAC-SHA256 verification |
| `ORDER_HMAC_MAX_SKEW_SECONDS` | `30` | Max clock skew / replay window in seconds |
| `ORDER_ALLOWED_IPS` | *(optional)* | Comma-separated IPs/CIDRs (e.g. `203.0.113.42,100.64.0.0/10`) |
| `ORDER_TRUST_PROXY_HEADERS` | `false` | Set `true` only behind a trusted reverse proxy (Nginx/Caddy) |
| `ORDER_TRUSTED_PROXIES` | `127.0.0.1/32,::1/128` | Proxy IPs permitted to supply `X-Forwarded-For` |
| `ORDER_RATE_LIMIT_PER_MINUTE` | `60` | Per-IP sliding-window request limit (`0` disables) |
| `ORDER_MAX_BODY_BYTES` | `65536` | Max HTTP payload size (`413` if exceeded) |
| `ORDER_ENABLE_DOCS` | `false` | Keeps `/docs` & `/openapi.json` hidden in production |

### 4. Run the Server

```bash
export ORDER_CLIENT_ID="<your-internal-client-id>"
export ORDER_API_KEY="<generated-api-key>"
export ORDER_HMAC_SECRET="<generated-hmac-secret>"
export ORDER_ALLOWED_IPS="<authorized-person-ip-or-tailscale-cidr>"
uvicorn trade_order_engine.api.app:app --host 127.0.0.1 --port 8000
```

> **Production Hosting Tip:** Bind `uvicorn` to `127.0.0.1:8000` behind **HTTPS** (Nginx/Caddy) or a private mesh VPN (Tailscale/WireGuard), keep `ORDER_ENABLE_DOCS=false`, and enable `ORDER_API_KEY` + `ORDER_HMAC_SECRET` + `ORDER_ALLOWED_IPS` together.

## API Endpoints

| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | IP/Rate | Minimal liveness check (`{"status": "ok"}`) |
| `POST` | `/orders` | Required | Validate and place a single order (`ORDER_TYPE = 'L'`) |
| `POST` | `/orders/batch` | Required | Validate and write multiple legs atomically (`ORDER_TYPE = 'L'`) |
| `GET` | `/orders` | Required | List rows (filter by `stg_id`, `side`, `order_type`, `limit`) |
| `GET` | `/orders/{uniq_no}` | Required | Fetch latest state of an order by `uniq_no` |
| `PATCH` | `/orders/{uniq_no}` | Required | Validate and append a modify row (`ORDER_TYPE = 'M'`) |
| `DELETE` | `/orders/{uniq_no}` | Required | Validate and append a cancel row (`ORDER_TYPE = 'C'`) |

### Example `curl` Requests

**Place a Market order (`PRICE = 0`, `ORDER_TYPE = "L"`):**
```bash
curl -X POST https://your-host/orders \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ORDER_API_KEY" \
  -d '{
    "uniq_no": 676,
    "contract": "NIFTY2690823850CE",
    "side": 2,
    "lot": 5,
    "price_type": "MARKET",
    "price": "0",
    "stg_id": 763,
    "note": "275.55"
  }'
```

**Place a Limit order (`PRICE > 0`, `ORDER_TYPE = "L"`):**
```bash
curl -X POST https://your-host/orders \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ORDER_API_KEY" \
  -d '{
    "uniq_no": 677,
    "contract": "NIFTY2690823850CE",
    "side": 2,
    "lot": 5,
    "price_type": "LIMIT",
    "price": "275.55",
    "stg_id": 763,
    "note": "entry"
  }'
```

**Modify an active order (`ORDER_TYPE = "M"`):**
```bash
curl -X PATCH https://your-host/orders/677 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ORDER_API_KEY" \
  -d '{"lot": 10, "price": "276.25"}'
```

**Cancel an active order (`ORDER_TYPE = "C"`):**
```bash
curl -X DELETE https://your-host/orders/677 \
  -H "X-API-Key: $ORDER_API_KEY"
```

### Example Python Client (API Key + HMAC-SHA256 Signing)

```python
import json
import httpx
from trade_order_engine.security import sign_request

API_KEY = "<ORDER_API_KEY>"
HMAC_SECRET = "<ORDER_HMAC_SECRET>"

body = json.dumps({
    "contract": "NIFTY2690823850CE",
    "side": "SELL",
    "lot": 5,
    "price_type": "MARKET",
    "price": "0",
    "stg_id": 763,
    "note": "275.55",
}).encode("utf-8")

timestamp, signature = sign_request(
    secret=HMAC_SECRET,
    method="POST",
    path_with_query="/orders",
    body=body,
)

resp = httpx.post(
    "https://your-host/orders",
    content=body,
    headers={
        "Content-Type": "application/json",
        "X-API-Key": API_KEY,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    },
)
print(resp.status_code, resp.json())
```

## Running Tests

```bash
pytest -v
```
