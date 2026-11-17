# Battleship AI Hackathon: 3D Replay Viewer

Two Battleship bots play each other, and this project turns the match into a
naval battle you can watch: fleets sail in, shells arc across the water, ships
burn and sink.

![Aerial view of a match in progress](docs/images/aerial.png)

It started as a club hackathon where members wrote Battleship bots and ran them
against each other. This repository adds a way to *show* a match, so it can be
recorded and shared.

![Slow-motion close-up of a ship being sunk](docs/images/closeup.png)

## What it does

1. **Record.** `scripts/export_replay.py` runs one match between any two bots
   and saves a replay: where each bot placed its ships, every shot in order
   with its result, and the winner.
2. **Play back.** `viewer/index.html` reads that replay and animates it in the
   browser. Nothing in the viewer decides the game; it only follows the
   recorded shots.

The viewer is a single HTML file using [Three.js](https://threejs.org/). The
ships, water, effects and sound are all generated in code, so there are no
models, textures or audio files to download.

## Quick start

You need Python 3.11 to 3.13 and a modern browser.

```console
git clone https://github.com/TDRobertson/battleship-hackathon-render.git
cd battleship-hackathon-render
pip install -e .
```

Watch the included demo match by opening `viewer/index.html` in your browser.
The page loads Three.js and a font from a CDN, so it needs an internet
connection.

Record a different match and watch it:

```console
python scripts/export_replay.py --bot-a hunt-target --bot-b starter --seed 7
```

This overwrites `viewer/replay.json` and `viewer/replay.js`. Reload the page to
see the new match.

### Recording your own bots

Bot arguments work the same way as in the hackathon kit: a built-in name
(`starter`, `hunt-target`) or `module:Class` for a bot file in the repository
root.

```console
python scripts/export_replay.py --bot-a my_bot:MyAgent --bot-b other_bot:OtherAgent --name-a "Team One" --name-b "Team Two"
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--bot-a`, `--bot-b` | `hunt-target` | The two bots. Bot A shoots first. |
| `--name-a`, `--name-b` | the bot spec | Names shown on screen. |
| `--seed` | `2026` | Seeds both bots, so the same seed gives the same match. |
| `--out` | `viewer/replay.json` | Where to write the replay. |

To write a bot, see the [hackathon kit guide](docs/hackathon_kit.md) and
[`docs/tutorial_build_bot.md`](docs/tutorial_build_bot.md).

## Using the viewer

| Control | Key | What it does |
| --- | --- | --- |
| Restart | | Play the match again from the sail-in. |
| Pause | Space | Freeze and resume. |
| Speed | | Cycle 1x, 2x, 4x, 0.5x. |
| Sound | M | Turn sound on or off. Browsers keep it off until you click. |
| Loop | | Restart automatically after the winner card. |
| Load replay | | Open any replay `.json` without re-running the exporter. |
| Hide controls | H | Hide the buttons for a clean recording. |

The layout follows the window shape: a wide window gives a landscape view, a
tall one gives a portrait view suited to vertical video.

### Recording a video

1. Size the browser window to the shape you want.
2. Click **Sound**, then press **H** to hide the controls.
3. Click **Restart** (press H again to reach it) and capture the window with a
   screen recorder such as OBS or the Windows Game Bar (Win+Alt+R).

### Tuning

A few constants at the top of the script in `viewer/index.html` control the
feel:

| Constant | Default | Effect |
| --- | --- | --- |
| `TARGET_BATTLE` | `42` | Target length of the battle in seconds; shot pacing is scaled to fit. |
| `INTRO` | `7.0` | Length of the sail-in. |
| `CINE_CHANCE` | `0.35` | Chance that a sinking gets a slow-motion close-up. The last one always does. |
| `CINE_SLOW` | `0.28` | Time scale during a close-up. |

## Replay format

A replay is one JSON object. Coordinates are zero-based `[row, col]`.

```json
{
  "version": 1,
  "seed": 2,
  "rules": { "rows": 10, "cols": 10, "fleet": [5, 4, 3, 3, 2] },
  "players": { "A": { "name": "Bot Alpha", "bot": "hunt-target" }, "B": { "name": "Bot Bravo", "bot": "hunt-target" } },
  "placements": { "A": [ { "slot": 0, "length": 5, "cells": [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]] } ], "B": [] },
  "shots": [ { "turn": 1, "player": "A", "row": 9, "col": 5, "outcome": "hit", "sunk": null } ],
  "winner": "B",
  "reason": "all ships sunk",
  "turns": 72
}
```

`outcome` is `miss`, `hit` or `sunk`. When a ship is sunk, `sunk` holds its
`slot` and `cells`.

## Project layout

```text
viewer/
|-- index.html            # The 3D replay viewer (single file)
|-- replay.json           # The current replay
`-- replay.js             # Same replay as a script, so the page works from disk

scripts/
|-- export_replay.py      # Records a match to viewer/replay.json
`-- organizer_*.py        # Tournament helpers from the hackathon kit

src/                      # Hackathon kit: game engine, match runner, bot SDK
examples/                 # Hackathon kit: example bots and snippets
tests/                    # Hackathon kit: test suite
docs/
|-- hackathon_kit.md      # Original kit README: installing, running, writing bots
|-- rules.md              # Game rules
`-- ...                   # Remaining kit documentation
```

The viewer and exporter are additions. The game engine is unchanged; the
exporter only listens to the spectator hooks the match runner already provides.

## Status

- The included demo is a match between two copies of the kit's `hunt-target`
  reference bot, not hackathon entries.
- Sound and visuals are synthesised and deliberately stylised.
- The viewer is display-only; there is no interactive play.

## Credits

Built on the [Battleship AI Hackathon Kit](https://github.com/mjessey/battleship-hackathon)
by Maximus Jessey, which provides the game engine, bot SDK and tournament
tools. Its documentation is kept in [`docs/`](docs/hackathon_kit.md).
