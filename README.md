# Movie Night Decider

**Language:** Python (FastAPI) &nbsp;|&nbsp; **Needs:** Postgres + Redis

This is a **starter**. The application already works. Your job is everything
that gets it building, tested and running in CI.

---

## You do not need Python installed

You will build this into a container, and the container brings its own
Python 3.12. You are not being asked to extend the app — you are being asked
to ship it.

---

## 1. What this app needs

| | |
|---|---|
| **Runtime** | Python 3.12 |
| **Install dependencies** | `pip install -r requirements.txt` |
| **Start the app** | `uvicorn app.main:app --host 0.0.0.0 --port 8080` |
| **Listens on** | port 8080, bound to `0.0.0.0` |
| **Environment variables** | `DATABASE_URL`, `REDIS_URL` |
| **Needs running first** | Postgres, Redis, and the migrations applied |

### What it does

Someone opens a poll, everyone adds films and ranks them. When the poll closes the app runs a real instant-runoff count instead of just picking whatever had the most first-place votes, and shows you every elimination round - who went out, where their votes went, and what the majority bar was at the time.

### Endpoints

```
GET  /health
GET  /polls
POST /polls                   {"title":"Friday night","opened_by":"asha"}
GET  /polls/{id}              films, live first-preference counts, ballots cast
POST /polls/{id}/films        {"title":"Dune: Part Two","added_by":"rahul"}
POST /polls/{id}/ballots      {"voter":"asha","ranking":[3,1,2]}
POST /polls/{id}/close        runs the count, exactly once
GET  /polls/{id}/results      the stored round-by-round history
```

`/health` reports Postgres and Redis **separately**. If it says
`postgres: false` the app started fine and your compose wiring is wrong —
do not go looking in the application code.

### Migrations

`migrations/` holds `.sql` files applied **in filename order** before the app
starts. They create the tables and insert sample data. A container running
`psql` over them in order is enough; you do not need a migration tool.

---

## 2. What you must write

| File | What it has to do |
|---|---|
| `Dockerfile` | Install dependencies **before** copying source, pin the base image, do not run as root. |
| `docker-compose.yml` | App + Postgres + Redis + a migration step, one `docker compose up`. |
| `.circleci/config.yml` | lint → unit tests → integration tests → secret scan → image build |
| Unit tests | For `app/voting.py`. No database, no network. |
| Integration tests | Against a real Postgres and Redis as CircleCI service containers. |

Then push your image to **your own Docker Hub account**, tagged `:1.0`.

### When it works

```bash
docker compose up --build
curl localhost:8080/health
```

```json
{"status":"ok","postgres":true,"redis":true}
```

---

## Where the marks are

`app/voting.py` is **pure logic** — plain functions over plain data, no
database and no HTTP. Start your tests there. Use pytest:
`pytest --cov=app --cov-report=term-missing`. Minimum 70%.

The seeded poll 1 is built so the plurality winner and the instant-runoff winner are different films, and so round one has a two-way tie at the bottom. Assert both. Then write the ugly ones: three films all tied, every ballot exhausting at once, a poll with one film, a poll with none.

## Why Redis is here

Two different jobs. A hash of live first-preference counts, so the room can watch the poll fill up without re-aggregating the ballots table on every refresh - it is warmed from Postgres if the cache is cold. And a `SET NX EX` lock around closing, so two people hitting Close at the same moment cannot both run the count. Note that the lock alone is not enough: it expires. The conditional `UPDATE ... WHERE status='open'` is what actually makes it exactly once.

## The hard part

Ties at the bottom. Two films on two votes each - which goes out? Pick a rule and defend it.

Write your answer in your README. It is worth more marks than the feature.

---

## Getting unstuck

| Symptom | Almost always |
|---|---|
| `/health` says `postgres: false` | Wrong hostname. In compose the host is the **service name**, not `localhost`. |
| Page will not load, logs fine | No `ports:` mapping, or bound to `127.0.0.1` not `0.0.0.0`. |
| `relation "..." does not exist` | Migrations did not run, or the app started before they finished. |
| Build takes minutes each time | `COPY . .` is above your dependency install. |
| CI cannot reach the database | In CircleCI service containers the host **is** `localhost` — opposite of compose. |
