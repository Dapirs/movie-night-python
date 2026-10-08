"""Pure instant-runoff counting. No database, no HTTP.

Everyone ranks the films. Count the first preferences. If nothing has a
majority, knock out the weakest film and give each of its ballots to that
voter's next surviving choice. Repeat. The winner is whatever is still
standing when something crosses half.

That description hides four decisions, and they are the whole assignment:

* MAJORITY OF WHAT? A ballot whose every choice has been eliminated is
  "exhausted" and counts for nobody. If the threshold stays pinned to the
  number of ballots cast, a round can end with nobody able to reach it. It is
  recomputed each round against the ballots still live. That means the bar
  can fall between rounds, and you should be able to say why that is right.

* WHO GOES OUT ON A TIE? Two films on two votes each. `break_tie` does a
  countback: look at the previous round, then the one before, and eliminate
  whoever was weaker earliest. If every past round had them level too, fall
  back to stable order. Never random - the same ballots must always give the
  same answer, or nobody will believe the result.

* CAN YOU ELIMINATE SEVERAL AT ONCE? If the tied-lowest films put together
  still have fewer votes than the next film up, none of them could ever
  overtake it, so they can all go in one round. `can_batch_eliminate` says
  when that is safe. It is faster and it is a legitimate alternative answer
  to the tie question.

* WHAT IF EVERYTHING IS TIED? Then there is no winner, and saying so is
  better than eliminating at random. `count` returns status "tie".

Worth testing: an outright first-round majority; the plurality leader losing
to IRV (that is the whole point of the method - `plurality_winner` is here so
you can assert the two disagree); a two-way bottom tie; a tie the countback
resolves; a tie nothing resolves; every ballot exhausting; a single
candidate; zero ballots; a ballot that repeats a film; a ballot naming a film
that is not in the poll; and that `count` called twice on the same input
returns byte-identical rounds.
"""

class BallotError(ValueError):
    pass


def clean_ballot(ranking, candidates, strict=True):
    """Normalise one ballot into a tuple of candidates, best first.

    Duplicates keep their first position - ranking Dune 1st and 3rd means
    1st. With strict=False, names not in the poll are dropped instead of
    raising, which is what you want when a film is deleted mid-poll.
    """
    allowed = set(candidates)
    out = []
    for c in (ranking or []):
        if c not in allowed:
            if strict:
                raise BallotError(f"{c!r} is not in this poll")
            continue
        if c not in out:
            out.append(c)
    return tuple(out)


def tally(ballots, candidates, eliminated=()):
    """First preferences among the survivors, plus the exhausted count."""
    dead = set(eliminated)
    counts = {c: 0 for c in candidates if c not in dead}
    exhausted = 0
    for b in ballots:
        choice = next((c for c in b if c not in dead), None)
        if choice is None:
            exhausted += 1
        else:
            counts[choice] += 1
    return counts, exhausted


def majority_threshold(active):
    """Strictly more than half of the ballots still live, as a whole number.

    10 live ballots -> 6. 11 -> 6. Note that 5 of 10 is not a majority.
    """
    active = int(active)
    return (active // 2) + 1 if active > 0 else 0


def lowest_candidates(counts):
    """Everyone sharing the smallest tally this round."""
    if not counts:
        return []
    floor = min(counts.values())
    return sorted([c for c in counts if counts[c] == floor], key=str)


def break_tie(tied, history):
    """Decide which of the tied-lowest films is eliminated.

    `history` is the tallies of every completed round, oldest first, not
    including the round being decided. Walk backwards: the film that was
    weakest in the most recent round where they differed goes out. If they
    were level in every single round - including round one - nothing in the
    ballots separates them, so fall back to stable order and say so.

    Returns (candidate, reason).
    """
    pool = sorted(tied, key=str)
    if not pool:
        raise BallotError("nothing to break a tie between")
    if len(pool) == 1:
        return pool[0], "only one film had the lowest count"
    for depth, past in enumerate(reversed(history), start=1):
        floor = min(past.get(c, 0) for c in pool)
        narrowed = [c for c in pool if past.get(c, 0) == floor]
        if len(narrowed) < len(pool):
            pool = narrowed
            if len(pool) == 1:
                return pool[0], f"countback: weaker {depth} round(s) earlier"
    return pool[0], ("level in every round - broken by stable order, "
                     "so the same ballots always give the same result")


def can_batch_eliminate(counts, tied):
    """Is it safe to drop every tied-lowest film in one round?

    Only if their votes combined still cannot reach the next film up. If they
    could, one of them might have overtaken it after transfers, and knocking
    them all out would have changed the result.
    """
    others = [v for c, v in counts.items() if c not in set(tied)]
    if not others:
        return False
    return sum(counts[c] for c in tied) < min(others)


def plurality_winner(ballots, candidates):
    """Most first preferences, full stop. Here only so you can show that it
    disagrees with the instant-runoff result - which is the entire argument
    for doing this the hard way."""
    counts, _ = tally(ballots, candidates)
    if not counts:
        return None
    best = max(counts.values())
    top = sorted([c for c in counts if counts[c] == best], key=str)
    return top[0] if len(top) == 1 else None


def count(ballots, candidates, batch=False):
    """Run the whole count.

    Returns {"status", "winner", "rounds", "plurality_winner"}. status is
    "majority" (somebody crossed the line), "last_standing" (everyone else
    was eliminated), "tie" (nothing separated the survivors) or "exhausted"
    (every ballot ran out of choices).

    Every round is recorded, because "Spirited Away won" is not an answer
    anybody accepts - "Paddington went out in round one, both its ballots
    went to Spirited Away, which then passed Dune in round three" is.
    """
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        raise BallotError("a poll needs at least one film")
    ballots = [clean_ballot(b, candidates, strict=False) for b in ballots]

    eliminated, rounds, history = [], [], []
    while True:
        counts, exhausted = tally(ballots, candidates, eliminated)
        active = sum(counts.values())
        threshold = majority_threshold(active)
        surviving = sorted(counts, key=lambda c: (-counts[c], str(c)))
        rec = {"round": len(rounds) + 1,
               "tallies": dict(counts),
               "standings": surviving,
               "active": active,
               "exhausted": exhausted,
               "threshold": threshold,
               "eliminated": [],
               "reason": "",
               "winner": None}

        if active == 0:
            rec["reason"] = "every ballot ran out of surviving choices"
            rounds.append(rec)
            return _done("exhausted", None, rounds, ballots, candidates)

        leader = surviving[0]
        if counts[leader] >= threshold:
            rec["winner"] = leader
            rec["reason"] = (f"the leader has {counts[leader]} of {active} live "
                             f"ballots, and {threshold} was a majority")
            rounds.append(rec)
            return _done("majority", leader, rounds, ballots, candidates)

        if len(counts) == 1:
            rec["winner"] = leader
            rec["reason"] = "nothing else was left standing"
            rounds.append(rec)
            return _done("last_standing", leader, rounds, ballots, candidates)

        tied = lowest_candidates(counts)
        if len(tied) == len(counts):
            rec["reason"] = ("every surviving film has the same count - "
                             "eliminating one would be picking the winner by coin toss")
            rounds.append(rec)
            return _done("tie", None, rounds, ballots, candidates)

        if batch and can_batch_eliminate(counts, tied):
            rec["eliminated"] = list(tied)
            rec["reason"] = (f"{len(tied)} films share the lowest count "
                             f"({counts[tied[0]]}) and cannot reach the next film even "
                             "combined, so they all go at once")
        else:
            out, why = break_tie(tied, history)
            rec["eliminated"] = [out]
            rec["reason"] = (f"eliminated on the fewest votes ({counts[out]})"
                             if len(tied) == 1 else
                             f"{len(tied)} films tied on {counts[out]} - {why}")
        eliminated.extend(rec["eliminated"])
        history.append(dict(counts))
        rounds.append(rec)


def _done(status, winner, rounds, ballots, candidates):
    return {"status": status,
            "winner": winner,
            "rounds": rounds,
            "plurality_winner": plurality_winner(ballots, candidates)}


def describe(result, names=None):
    """One readable line per round, for people who will not read JSON."""
    label = (lambda c: str(names.get(c, c))) if names else (lambda c: str(c))
    lines = []
    for r in result["rounds"]:
        order = ", ".join(f"{label(c)} {r['tallies'][c]}" for c in r["standings"])
        gone = ", ".join(label(c) for c in r["eliminated"])
        lines.append(f"Round {r['round']}: {order}"
                     + (f" (exhausted {r['exhausted']})" if r["exhausted"] else "")
                     + (f" | out: {gone}" if gone else "")
                     + f" - {r['reason']}")
    if result["winner"] is not None:
        lines.append(f"Winner: {label(result['winner'])} ({result['status']})")
    else:
        lines.append(f"No winner: {result['status']}")
    return lines
