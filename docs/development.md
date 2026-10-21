# Development

Core engine code is independent of PyGame and process management. Prefer tests
against the engine, observations, and runner before changing UI behavior.

Run:

```console
pytest
```

Install the `dev` extra before auditing helper contracts. It includes
Hypothesis, which runs the property-based tests for SDK helper invariants:

```console
pip install -e ".[dev]"
pytest tests/unit/test_board_helpers.py tests/unit/test_placement_helpers.py tests/unit/test_targeting_helpers.py tests/unit/test_summary_validation_helpers.py tests/unit/test_neural_helpers.py
```

Helper behavior is specified in `docs/helper_contracts.md`. When adding or
changing helpers, update the contract first, then add example and property tests
that trace back to it.

For headless PyGame checks, set `SDL_VIDEODRIVER` before running tests.

Windows PowerShell:

```powershell
$env:SDL_VIDEODRIVER = "dummy"
pytest
```

macOS/Linux:

```sh
SDL_VIDEODRIVER=dummy pytest
```
