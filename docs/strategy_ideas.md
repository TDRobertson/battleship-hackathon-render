# Strategy Ideas, Not Solutions

These prompts are meant to help teams diverge. They are not official answers,
and many of them conflict with each other. Pick a hypothesis, test it, and keep
the version that wins more often.

## Placement

- Spread ships apart so random hits reveal less structure.
- Cluster ships to make the opponent over-trust local search.
- Bias ships toward edges or corners.
- Maintain a small portfolio of hand-written layouts and choose between them.
- Mirror or rotate layouts to avoid repeating the same pattern.
- Design placements that perform well against your current local opponents, then
  check whether they still work against different opponents.

## Hunting

- Try checkerboard, center-first, edge-first, or randomized search orders.
- Change hunting behavior as smaller ships sink.
- Compare deterministic search patterns with randomized candidate pools.
- Track which cells your strategy tends to leave until late and ask whether that
  creates weaknesses.

## Finishing Ships

- After a hit, decide whether to prioritize neighbors immediately or keep hunting.
- Treat adjacent hits as one possible ship, but remember touching ships are legal.
- Experiment with when to follow a line and when to branch.
- Use remaining ship lengths to rule out impossible lines.

## Probability And Inference

- Count possible ship placements consistent with known misses and hits.
- Compare "shoot most likely hit" against "shoot most informative cell."
- Blend probability with geometry, center bias, or randomness.
- Cap expensive searches and study whether approximate answers are good enough.

## Opponent Modeling

- Watch whether a bot favors parity, center cells, or local hit chasing.
- Build placements that punish the most common opponent behavior in your test set.
- Run the same bot from both player orders to separate first-player advantage
  from real strategy strength.

## Learning

- Change observation channels and compare learning curves.
- Add channels for which specific ship slots are still unsunk.
- Try different reward shapes for misses, hits, sinks, and wins.
- Train against one opponent, then evaluate against several different opponents.
- Train against random previous versions of your own policy to avoid only
  overfitting to one fixed opponent.
- Let a placement policy choose among several legal fleet layouts, then reward
  layouts that take opponents longer to sink.

## Experiment Habits

- Change one idea at a time.
- Keep seeds fixed while debugging, then test with new seeds.
- Use CSV output to compare enough games that luck matters less.
- Save surprising losses and inspect what assumption failed.
