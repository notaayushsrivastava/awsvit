# LiveBid

Real-time auction backend demonstrating correct shared-state updates under
concurrency: Flask + Flask-SocketIO + PostgreSQL, Jinja + Tailwind frontend.

> The database decides what happened. Flask-SocketIO makes everyone find out immediately.

## Architecture

```
app/
├── __init__.py            # app factory
├── extensions.py          # db, migrate, socketio singletons
├── models.py              # Auction, Bidder, AuctionParticipant, Bid, AuctionEvent
├── routes.py              # HTTP pages + state API
├── sockets.py             # Socket.IO handlers (thin transport layer)
├── closer.py              # deadline watcher: closes expired auctions, broadcasts
├── services/
│   └── auction_service.py # ALL auction logic (HTTP + sockets call this)
├── templates/             # Jinja + Tailwind (minimalist)
└── static/js/auction.js   # vanilla JS realtime client
```

Concurrency discipline: every bid runs in one transaction —
`SELECT ... FOR UPDATE` on the auction row, re-validate against
authoritative state (status, server-time deadline, minimum increment,
membership, request-id idempotency), write, commit — and only then broadcast.

## Running

```bash
# 1. PostgreSQL

# Option A: Docker
docker run -d --name livebid-db -e POSTGRES_PASSWORD=livebid \
  -e POSTGRES_USER=livebid -e POSTGRES_DB=livebid -p 5432:5432 postgres:16-alpine

# Option B: native PostgreSQL installation
# Install PostgreSQL from https://www.postgresql.org/download/ and run:
psql -U postgres

CREATE USER livebid WITH PASSWORD 'livebid';
CREATE DATABASE livebid OWNER livebid;
CREATE DATABASE livebid_test OWNER livebid;
\q

# Option C: hosted PostgreSQL
# Set DATABASE_URL and TEST_DATABASE_URL to connection strings supplied by
# your provider. The application does not require PostgreSQL to run locally.

# 2. Python deps
pip install -r requirements.txt

# 3. Database schema
export FLASK_APP=run.py
flask db upgrade

# 4. Run
python run.py           # http://localhost:5000
```

For native PostgreSQL on Windows, run the commands above in `psql` after
installing PostgreSQL and adding its `bin` directory to `PATH`. On macOS or
Linux, PostgreSQL can also be installed through the platform package manager.
The default local connection is
`postgresql+psycopg://livebid:livebid@localhost:5432/livebid`; override it
with `DATABASE_URL` when using different credentials, a different host, or a
hosted database. Tests use `TEST_DATABASE_URL` and default to the
`livebid_test` database.

## Tests

```bash
python -m pytest tests -q
```

Covers bid validation, idempotency, expiry, concurrent bids (10/20/50 via
real threads against real PostgreSQL row locks), bid-vs-close races,
duplicate request IDs, room isolation, disconnect/reconnect recovery.
