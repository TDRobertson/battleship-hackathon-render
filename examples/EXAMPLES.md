# Examples

These are teaching examples. Some are small snippets, and some are complete
importable bots. Copy pieces into your own bot and change the strategy.

- `candidate_scoring.py`: rank candidate shots without choosing the strategy
  for you.
- `complete_bot.py`: a complete, documented `Agent` that you can simulate
  directly.
- `custom_placement.py`: build a small placement portfolio.
- `heatmap_inference.py`: combine fleet-sample heatmaps with information
  scores.
- `ml_reinforce_target.py`: train a small policy model from target-practice
  rewards.
- `ml_supervised_occupancy.py`: train a small model to approximate SDK
  occupancy maps.
- `neural_channels.py`: customize shooting and placement neural observations.
- `opponent_memory_bot.py`: use persistent per-opponent memory safely.
- `bots.txt`: sample tournament bot list.

Run the complete examples from the project root:

```console
battleship simulate --bot-a examples.complete_bot:DocumentedExampleBot --bot-b hunt-target --games 20
battleship simulate --bot-a examples.opponent_memory_bot:MemoryExampleBot --bot-b hunt-target --games 20
```

Run the machine-learning examples after installing the optional ML extra:

```console
pip install -e ".[dev,ui,ml]"
python examples/ml_supervised_occupancy.py
python examples/ml_reinforce_target.py
```

For adaptive bots, see `docs/opponent_memory.md`. It explains persistent
per-opponent memory, first-match cold starts, and safe defaults when memory is
empty.

## Setup

Run snippets from the project root after installing the repo.

With `venv`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,ui]"
```

With `conda`:

```powershell
conda create -n battleship python=3.11
conda activate battleship
python -m pip install --upgrade pip
pip install -e ".[dev,ui]"
```
