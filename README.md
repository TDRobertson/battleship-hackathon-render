# Battleship AI Hackathon Kit

Build a Python bot for Battleship, run it locally, play against it, and compare
it with other bots. The project is designed for university hackathons: the
engine enforces the rules, the SDK handles board bookkeeping, and participants
own the strategy.

## The Game

Battleship is played on a 10 by 10 grid with zero-based `(row, col)`
coordinates. Each player places ships of lengths `[5, 4, 3, 3, 2]`. Ships may
touch, but they may not overlap.

Players alternate shots. A shot returns `miss`, `hit`, or `sunk`. A sunk result
reveals the full sunk ship. Repeated shots, illegal placements, bot crashes, and
timeouts lose the current game immediately. Each bot has 5 seconds for placement
and 0.5 seconds for each shot, with no cumulative game clock. See `docs/rules.md`
for the complete rules summary.

## Installation

Requirements:

- Python 3.11, 3.12, or 3.13
- `pip`

Python 3.14 and newer are not documented as supported for this kit yet because
the optional UI depends on pygame, and pygame wheels may lag new Python
releases. Use Python 3.11 for the smoothest event setup.

Package requirements:

| Install extra | Packages | Needed for |
| --- | --- | --- |
| Base | `numpy>=1.24` | Engine, SDK helpers, bots, simulations |
| `dev` | `pytest>=7.4`, `hypothesis>=6.88` | Tests and helper-contract checks |
| `ui` | `pygame>=2.5` | `battleship play` and target-practice UI |
| `ml` | `torch>=2.0`, `matplotlib>=3.7` | Machine-learning helpers, tensors, and plots |

Optional but recommended: create a virtual environment first. Use either
`venv` or `conda`.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,ui]"
```

macOS/Linux:

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev,ui]"
```

Conda:

```console
conda create -n battleship python=3.11
conda activate battleship
python -m pip install --upgrade pip
pip install -e ".[dev,ui]"
```

If you do not want a virtual environment, run only:

```console
pip install -e ".[dev,ui]"
```

## Bare Bones Usage

Run a starter-bot match:

```console
battleship simulate --games 5 --bot-a starter --bot-b hunt-target --verbose
```

Play against your bot:

```console
battleship play --bot starter
```

The play screen includes a right-side debug panel for helper overlays such as
occupancy heatmaps, diagonal bands, hit-neighbor candidates, line extensions,
and neural observation channels.

Practice against a random hidden fleet with no opponent:

```console
battleship play --solo
```

Build your first bot:

Windows PowerShell:

```powershell
Copy-Item src\bots\starter_random.py my_bot.py
```

macOS/Linux:

```sh
cp src/bots/starter_random.py my_bot.py
```

Then run it:

```console
battleship simulate --bot-a my_bot:RandomStarterBot --bot-b hunt-target --games 10
```

Then edit `my_bot.py`. Your first useful changes usually belong in
`place_ships` or `choose_shot`.

For LAN matches, start `battleship remote-server` on the host and open
`http://localhost:8765/` there to watch. Competitors connect with
`battleship remote-client`; the host can list players with `remote-list` and
running series with `remote-matches`. Start a double-elimination tournament with
`battleship tournament --server http://HOST:8765`. Remote placement has a
5-second limit and each shot has a 0.5-second limit. See [Remote LAN Matches](docs/remote_play.md) for setup,
reconnection, timeouts, and organizer commands.

To try the live tournament dashboard with nine local bots, run
`battleship demo-tournament` and open the printed URL. Add `--port 8765` to use
`http://localhost:8765/`.

Run tests before submitting or sharing changes:

```console
pytest
```

## Learning Path

For the first 30 minutes, read only:

1. `docs/rules.md`: official rules.
2. `docs/tutorial_build_bot.md`: copy and improve a simple bot.
3. `docs/running_matches.md`: run, play, compare, and submit locally.

Use these when you need them:

4. `docs/sdk_helpers.md`: toolbox reference.
5. `docs/neural_networks.md`: neural observations, rewards, and self-play.
6. `docs/strategy_ideas.md`: prompts for different approaches.
7. `docs/remote_play.md`: LAN server/client setup for remote bots.
8. `docs/development.md`: testing and maintainer notes.

Teaching snippets and complete example bots live in `examples/`. Organizer
scripts live in `scripts/`.

## Bot Interface

Implement `agent.Agent`:

```python
from agent import Agent


class MyAgent(Agent):
    def place_ships(self, rules, time_remaining):
        ...

    def choose_shot(self, observation, time_remaining):
        ...
```

`observation` is a public snapshot of your target board. It contains masks for
`misses`, unresolved `hits`, `sunk` cells, and `ships_alive`. It never reveals
unhit enemy ship cells. `time_remaining` is the per-action limit: normally 5
seconds for placement and 0.5 seconds for a shot. Remote matches include network time.

## Built-In Bots

- `starter`: alias for the minimal random starter.
- `starter-random`: minimal blank-slate legal bot.
- `hunt-target`: fires near unresolved hits before returning to random hunting.

You can also load your own bot with `module:Class`, for example:

```console
battleship simulate --bot-a my_bot:MyAgent --bot-b hunt-target --games 50
```

## Project Map

```text
src/
|-- agent.py              # Participant-facing bot base class
|-- app/                  # Command-line interface implementation
|-- battleship/           # `python -m battleship` entry package
|-- bots/                 # Two small reference bots, not a strategy library
|-- core/                 # Authoritative rules and engine
|-- runtime/              # Match runner and subprocess worker
|-- sdk/                  # Neutral helpers for observations, placement, inference, validation
`-- ui/                   # PyGame human-vs-bot app and spectator dashboard

examples/
|-- EXAMPLES.md           # Example snippet overview
|-- bots.txt              # Sample tournament bot list
|-- candidate_scoring.py  # Candidate/scoring snippet
|-- complete_bot.py       # Complete documented Agent example
|-- custom_placement.py   # Placement portfolio snippet
|-- heatmap_inference.py  # Fleet-sampling shot-scoring snippet
|-- ml_reinforce_target.py      # Tiny policy-gradient training reference
|-- ml_supervised_occupancy.py  # Supervised occupancy-map training reference
|-- neural_channels.py    # Neural observation snippet
`-- opponent_memory_bot.py # Persistent-memory Agent example

scripts/
|-- organizer_local_tournament.py
|-- organizer_remote_round_robin.py
`-- organizer_remote_server.py

docs/
|-- agent_protocol.md     # Process and remote transport protocol notes
|-- development.md        # Testing and maintainer notes
|-- helper_contracts.md   # Behavioral contracts for SDK helpers
|-- opponent_memory.md    # Persistent per-opponent memory guidance
|-- rules.md              # Official rules summary
|-- tutorial_build_bot.md # First-bot walkthrough
|-- sdk_helpers.md        # Helper reference
|-- neural_networks.md    # Neural-network observation and training guide
|-- remote_play.md        # LAN server/client setup for remotely run bots
|-- strategy_ideas.md     # Prompts for varied bot designs
`-- running_matches.md    # Simulation, play, comparison, competition commands
```

## Testing

```console
pytest
```

For neural-network bots and training plots, install the optional ML dependencies:

```console
pip install -e ".[dev,ui,ml]"
```
