# QuestVerifier Decision Record

## The product

A bounty board where the thing being checked -- "does this tweet praise the project," "does this
PR fix the reported bug" -- is inherently a judgment call, not a fact any deterministic oracle can
certify. A creator posts a quest and reward, a claimant proves they control a qualifying post or
PR, and a consensus round decides whether it actually meets the quest's criteria.

## Counterfactual: why not just a keyword filter, or a single off-chain judge

A pure keyword filter ("must contain #genlayer") can be gamed trivially and can't tell a genuine
endorsement from a copy-pasted hashtag with no real content around it -- most quests worth running
need an actual reading of the page, not a substring match. A single off-chain judge (one server
deciding pass/fail) just relocates the trust problem: claimants would need to trust that one
operator not to be lazy, biased, or compromised, which is exactly the kind of single point of
failure a bounty board should not depend on. `gl.eq_principle.strict_eq` gives every validator the
same page render and the same prompt, and only accepts a verdict every validator reaches
identically -- so the judgment is real, but no single party makes it alone.

## Why the wallet-bound code and keyword checks are deterministic, not LLM-judged

Ownership and simple presence are facts, not judgment calls, and facts should never be left to a
model's discretion when plain code can check them exactly and more cheaply. The code is generated
from the claimant's own address (`GLQ-{quest_id}-{first 8 hex chars of address}`), so an LLM being
persuaded that "the code is probably there somewhere" can never substitute for the code actually
being on the page. This also shrinks what the LLM is asked to decide down to the one thing that
really does need judgment: does this specific page content satisfy this specific quest's
criteria.

## Why an unreachable proof page reverts instead of failing

A `fail` verdict consumes one of a claimant's three attempts; an `unreachable` verdict is an
infrastructure problem that has nothing to do with whether their proof is genuine. Charging a
claimant an attempt for a renderer hiccup would punish them for something entirely outside their
control, so `_run_check` returns a distinct `unreachable` status and `submit_proof` reverts on it
-- no submission record is written, no attempt is spent, and the claimant can simply retry.

## Why rejections are bounded, then routed to a human appeal

Both of this contract's possible mistakes are real: a false pass pays a bounty that shouldn't have
been paid, and a false fail costs a genuine claimant an attempt on a task they may have already
completed correctly. Because the automated check can be wrong in either direction, a claimant
gets three tries against transient misreadings, and after that (or after any single rejection,
if they'd rather not spend more attempts) can `appeal` to a human moderator instead of being
permanently locked out by a model's literal reading of an ambiguous page. The creator may approve
an appeal (they only ever gain by being generous to a real claimant) but may not reject one --
rejecting is the one lever a financially interested party should not hold alone.

## Why proofs are keyed by content id, not by URL string

An early draft treated a normalized URL as the proof's identity, which meant the same tweet could
be resubmitted under a harmless query-string variation, or a claimant could point a "generic"
quest's checker at a URL whose path segments still matched a used pattern. Tweets are now keyed by
their numeric status id and PRs by `owner/repo/pull/number`, extracted directly from the URL's
required shape -- the one fact that actually identifies "this specific post" or "this specific
PR," independent of how the URL happened to be typed.

## Why there is a fee, unlike ProofOfLifeVault in this series

A digital-inheritance vault has no shared infrastructure cost beyond the owner's own vault; a
bounty board's consensus rounds are a real, ongoing cost the protocol operator incurs on every
submission, regardless of outcome. `fee_bps` is capped at 10% and is charged once, at funding
time, on the deposit the creator was going to make anyway -- never on a claimant's payout -- so
the cost of running verification is borne by the party who benefits from having their quest
checked, not by the person trying to earn a bounty.

## Self-review pass: gaps found and fixed before any external review

1. `submit_proof`'s original draft treated any non-pass verdict, including a page that failed to
   render at all, as a plain rejection that spent one of the claimant's three attempts -- fixed by
   giving unreachability its own status that reverts instead.
2. The original proof-uniqueness key was the normalized URL, which a query-string variation could
   bypass -- fixed by extracting each kind's actual content id (tweet status id, PR
   owner/repo/pull/number) and keying on that instead.
3. `close_quest` did not check for in-flight appeals before zeroing a quest's escrow, which could
   have left a later-approved appeal with no funds to pay out of -- fixed by blocking `close_quest`
   while any appeal on that quest is still pending.
4. The initial LLM prompt did not explicitly warn that the wallet-bound code's mere presence is
   not itself evidence the quest's criteria were met -- fixed by stating that distinction directly
   in the prompt, since a model could otherwise treat "the code is there" as "so the rest must be
   genuine too."

## v0.3: a schema-compatibility pass

v0.2 parsed and ran correctly under plain Python and passed a full local test suite, but failed to
deploy with "Could not load contract schema" -- the schema introspection step is stricter than the
Python interpreter, and four things a normal Python file allows are not introspectable:

1. **Every public write/view/constructor parameter and return type must be one of the SDK's fixed-
   width types** (`u256`, `Address`, `str`, `bool`, `dict`, `list`, `None`). v0.2 used plain
   Python `int` throughout public signatures (`max_winners: int`, `quest_id: int`, `bps: int`,
   `offset: int`...) because that is what ordinary Python code would use -- but `int` has no fixed
   width for the schema to serialize, so introspection fails at the first such parameter it finds.
   Fixed by switching every `@gl.public.write` / `@gl.public.view` / `__init__` parameter and
   return annotation to `u256`, converting to plain `int` only inside the method body where
   ordinary arithmetic is needed. Private helper methods (no `@gl.public.*` decorator) keep plain
   `int` freely, since only the public surface is introspected.
2. **Wallet addresses in public signatures must be typed `Address`, not `str`.** v0.2 typed
   several parameters (`user`, `new_owner`) as `str` and converted them to `Address(...)` inside
   the method body -- functionally equivalent at runtime, but the schema needs the `Address` type
   declared on the signature itself to know how to validate and encode an incoming address.
3. **`gl.get_contract_at(...)` used for `withdraw()`'s native transfer is not part of the SDK.**
   Any outbound value transfer needs a declared `@gl.evm.contract_interface` (a `_Payee` class
   with empty `View`/`Write` inner classes, following this series' other contracts), instantiated
   with the destination address and called as `_Payee(addr).emit_transfer(value=amount)`.
4. **The `datetime` stdlib module is not available in this runtime.** v0.2 converted the
   contract-clock string to unix seconds via `datetime.fromisoformat(...).timestamp()` to compare
   quest deadlines. Fixed by keeping deadlines as plain ISO-8601 UTC strings end-to-end (as every
   other contract in this series already does for its own timestamps) and comparing them
   lexicographically -- a fixed-width ISO-8601 string sorts identically to its chronological
   order, so no date-arithmetic library is needed at all for a plain "has this deadline passed"
   check.

None of these changes altered the contract's actual rules or economics -- every check, every
error condition, and every payout path is identical to v0.2. This was purely a type-system and
API-surface correction to make the same logic actually deployable.
