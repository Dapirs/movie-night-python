CREATE TABLE IF NOT EXISTS polls (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    opened_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS films (
    id SERIAL PRIMARY KEY,
    poll_id INT NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    added_by TEXT NOT NULL DEFAULT 'anonymous');
CREATE UNIQUE INDEX IF NOT EXISTS films_unique ON films (poll_id, lower(title));

CREATE TABLE IF NOT EXISTS ballots (
    id SERIAL PRIMARY KEY,
    poll_id INT NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    voter TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (poll_id, voter));

-- One row per preference. rank 1 is the voter's favourite. The unique
-- constraint on (ballot_id, film_id) is what stops a ballot ranking the same
-- film twice and quietly counting double.
CREATE TABLE IF NOT EXISTS ballot_choices (
    ballot_id INT NOT NULL REFERENCES ballots(id) ON DELETE CASCADE,
    rank INT NOT NULL CHECK (rank >= 1),
    film_id INT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
    PRIMARY KEY (ballot_id, rank),
    UNIQUE (ballot_id, film_id));

CREATE INDEX IF NOT EXISTS films_poll ON films (poll_id);
CREATE INDEX IF NOT EXISTS ballots_poll ON ballots (poll_id);
