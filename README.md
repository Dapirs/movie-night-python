---

# Delivery notes

Everything below is what was added around the application: container, tests, pipeline,
promotion flow and Kubernetes. The application code itself is the starter plus two endpoints
(`PATCH /polls/{id}` to rename a poll and `DELETE /polls/{id}`) so that the API supports the
full create / read / update / delete cycle.

## Run it

```bash
docker compose up --build        # app + Postgres + Redis, migrations applied automatically
curl -i localhost:8080/health    # 200 with postgres:true, redis:true
curl localhost:8080/polls        # the three seeded polls
bash scripts/crud-demo.sh        # create, read, update, delete, with the rows shown in Postgres
docker compose down -v           # stop and delete the data volume
```

`db` and `redis` have healthchecks. A one-shot `migrate` service applies `migrations/*.sql` in
filename order and exits; the app waits for both databases to be healthy and for `migrate` to
finish (`service_healthy` / `service_completed_successfully`). A fresh clone needs no other step.

## Tests

| | Command | What it covers |
|---|---|---|
| Unit | `python -m pytest tests/unit -v --cov=app.voting --cov-fail-under=70` | `app/voting.py` only: pure functions, no database, no network |
| Integration | `python -m pytest tests/integration -v` | every endpoint, through FastAPI's in-process `TestClient`, against a real Postgres and a real Redis (no mocks) |

Integration tests need `DATABASE_URL` and `REDIS_URL`. Locally:

```bash
docker run -d --rm --name pg-test -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app -p 5432:5432 postgres:16-alpine
docker run -d --rm --name redis-test -p 6379:6379 redis:7-alpine
export DATABASE_URL=postgresql://app:app@localhost:5432/app REDIS_URL=redis://localhost:6379
python -m pytest tests/integration -v
```

The unit job measures coverage of `app.voting` rather than all of `app/`, because `main.py`,
`db.py` and `cache.py` need a database and are covered by the integration tests instead.
The only unit-uncovered lines are the `last_standing` branch, which cannot be reached: a single
surviving film always already holds a majority of the live ballots.

## How a tie is broken

1. **Countback.** Look at the previous round, then the one before it, and eliminate whichever
   tied film was weaker earliest.
2. **Stable order.** If the films were level in every round, fall back to a fixed order, so the
   same ballots always give the same result. It is never random.

Two consequences worth stating plainly:

- The fixed order compares film ids **as text**, so `"10"` sorts before `"9"`. That is
  arbitrary, but it is deterministic, and it only applies after countback has failed. I chose
  to keep this behaviour and pin it with three tests rather than change application behaviour;
  switching to numeric order would mean updating those three tests.
- The majority threshold is recomputed each round over the ballots still live, because a ballot
  whose choices have all been eliminated is exhausted and counts for nobody. So the bar can fall
  between rounds, which is correct: otherwise a round could end with nobody able to reach it.

## Pipeline (CircleCI)

| Branch | What runs |
|---|---|
| `main` | secret scan -> lint -> unit tests -> integration tests -> build and push `:qa` |
| `staging` | build and push `:stage` (no tests, the same code already passed on `main`) |
| `prod` | build and push `:prod` |
| any other branch | the four checks only, nothing is pushed |

Each stage `requires` the previous one, so a failure stops everything after it. Every build
pushes two tags: the moving one (`qa` / `stage` / `prod`, what Kubernetes follows) and an
immutable `<branch>-<short-sha>`, which ties a running image back to a commit. Images are built
for `linux/amd64` and `linux/arm64`, because CircleCI is amd64 and the machines the cluster runs
on may be arm64. Docker Hub credentials are CircleCI project environment variables
(`DOCKERHUB_USER`, `DOCKERHUB_TOKEN`); nothing secret is in the repository, and the secret scan
checks the whole git history.

## Branches and promotion

`main` is QA, `staging` is pre-production, `prod` is production. A ruleset on all three blocks
direct pushes, force pushes and deletion, with an empty bypass list. Work arrives on a branch
and reaches `main` by pull request; promotion is `main` -> `staging` -> `prod`, always by pull
request and always with **Create a merge commit** (squashing would rewrite the commits into
new SHAs and leave the next promotion reporting conflicts). Right after a promotion
`git diff origin/main origin/staging` and `git diff origin/staging origin/prod` are empty.

## Kubernetes

One namespace per environment (`qa`, `stage`, `prod`), manifests in `k8s/<namespace>/`, identical
apart from the namespace and the image tag. Each namespace has Postgres, Redis and the app
(two replicas), each behind a Service, plus a `dockerhub` pull secret referenced through
`imagePullSecrets`. The app pulls `dapirs2006/movie-night-python:<qa|stage|prod>` with
`imagePullPolicy: Always`.

```bash
kubectl apply -f k8s/qa/
kubectl get pods,endpoints -n qa
kubectl port-forward -n qa svc/movie-night 8090:8080
```

Choices worth knowing:

- **Migrations** run in an init container on the app Pod, from a ConfigMap built out of
  `migrations/`. It waits for Postgres, then applies the files inside a single `psql` session
  holding an advisory lock. Without the lock, two Pods starting together on an empty database
  collided on `CREATE TABLE`: in a local test, 6 of 12 starts failed without it and 0 of 20
  failed with it.
- **Readiness probe only** on `/health`. If Postgres is down, restarting the app would not help,
  but taking it out of the Service is exactly right.
- **No fixed `nodePort`**, so the three namespaces cannot collide.
- **Postgres uses `emptyDir`**: data survives a container restart, not Pod deletion. The
  migrations rebuild the schema and seed data on the next start, but polls created in the
  meantime are lost. A PersistentVolumeClaim is the production answer.
- The database credentials in the manifests are throwaway values for a cluster that exposes no
  database port; real credentials would go in a Secret.

### Release loop and proof of what is running

```bash
# merge a pull request into main -> CircleCI builds and pushes :qa -> then:
kubectl rollout restart deployment/movie-night -n qa
kubectl rollout status deployment/movie-night -n qa
kubectl get pods -n qa -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}'
kubectl describe pod -n qa -l app=movie-night | grep -i "image id"
```

`rollout restart` rebuilds nothing: it replaces the Pods one at a time, and
`imagePullPolicy: Always` makes the new Pods pull whatever the tag points at now. The `Image ID`
digest must equal the `Digest:` printed at the end of that pipeline's `build-push` log.

## Known limitations

- The integration tests call the app in-process rather than over real HTTP to a container; the
  `docker compose` walkthrough and `scripts/crud-demo.sh` cover that path.
- GitHub requires a pull request but does not require the checks to pass before merging; that
  would be a "require status checks" rule on the ruleset.
- Promotion rebuilds the image on each branch instead of promoting the exact tested image.