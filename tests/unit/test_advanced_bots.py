import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from core.engine import GameEngine
from core.models import Outcome, Player, PublicShotResult, ShipPlacement, SunkShip
from core.rules import official_rules
from sdk.inference import (
    FleetSamplePool,
    fleet_pool_entropy,
    filter_possible_fleets,
    hypothesis_reduction_scores,
    normalize_alive_fleet,
    occupancy_from_fleets,
    occupancy_heatmap,
    possible_fleets,
    refill_possible_fleets,
    sample_possible_fleets,
)
from sdk.observation import ObservationState
from sdk.placement import ship_cells
from sdk.scoring import information_scores
from sdk.training import (
    MetricHistory,
    load_metrics_csv,
    match_history_from_csv,
    moving_average,
    save_comparison_plot,
    save_match_summary_plot,
    save_metric_plot,
)


def test_information_scores_are_available_without_bundling_information_bot():
    rules = official_rules()
    state = ObservationState(rules)
    fleets = sample_possible_fleets(rules, state.snapshot(), max_samples=25)
    heat = occupancy_from_fleets(rules, fleets)
    candidates = [(row, col) for row in range(rules.rows) for col in range(rules.cols)]
    info = information_scores(rules, fleets, candidates)

    assert info
    assert set(info) == set(candidates)
    assert max(info.values()) >= 0.0
    assert heat.shape == (rules.rows, rules.cols)


def test_hypothesis_reduction_scores_measure_posterior_entropy_drop():
    rules = official_rules()
    fleets = [
        (ShipPlacement(4, 0, 0, "horizontal"),),
        (ShipPlacement(4, 0, 1, "horizontal"),),
        (ShipPlacement(4, 5, 5, "horizontal"),),
        (ShipPlacement(4, 5, 6, "horizontal"),),
    ]
    candidates = [(0, 1), (5, 5), (9, 9)]

    hit_scores = hypothesis_reduction_scores(rules, fleets, candidates, assumed_outcome="hit")
    miss_scores = hypothesis_reduction_scores(rules, fleets, candidates, assumed_outcome=Outcome.MISS)
    expected_scores = hypothesis_reduction_scores(rules, fleets, candidates)

    prior_entropy = fleet_pool_entropy(rules, fleets)
    assert expected_scores[(0, 1)] > expected_scores[(9, 9)]
    assert hit_scores[(0, 1)] == pytest.approx(prior_entropy - fleet_pool_entropy(rules, fleets[:2]))
    assert miss_scores[(0, 1)] == pytest.approx(prior_entropy - fleet_pool_entropy(rules, fleets[2:]))
    assert hit_scores[(9, 9)] == 0.0
    assert miss_scores[(9, 9)] == pytest.approx(0.0)
    assert expected_scores[(9, 9)] == pytest.approx(0.0)


def test_hypothesis_reduction_scores_validate_assumed_outcome():
    rules = official_rules()
    fleets = [(ShipPlacement(4, 0, 0, "horizontal"),)]
    with pytest.raises(ValueError):
        hypothesis_reduction_scores(rules, fleets, [(0, 0)], assumed_outcome="maybe")


def test_metric_history_exports_series_and_csv():
    history = MetricHistory()
    history.log_many({"loss": 0.5, "accuracy": 0.6}, step=0, phase="train", run="supervised")
    history.log_many({"loss": 0.4, "accuracy": 0.7}, step=1, phase="validation", run="supervised")
    history.log("episode_reward", 3.0, step=0, phase="train", run="rl", episode=0, outcome="win")

    assert history.values("loss") == [0.5, 0.4]
    assert history.series("accuracy", phase="validation") == [(1, 0.7)]
    assert history.metric_names() == ["accuracy", "episode_reward", "loss"]
    assert moving_average([1, 3, 5], 2) == [1, 2, 4]

    output_dir = Path(".test-output")
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"metrics-{uuid4().hex}.csv"
    try:
        history.save_csv(path)
        loaded = load_metrics_csv(path)
        assert loaded.values("loss") == [0.5, 0.4]
        assert "run,step,episode,phase,name,value,outcome" in path.read_text()
    finally:
        path.unlink(missing_ok=True)
        cache_dir = Path(".matplotlib-cache")
        if cache_dir.exists():
            for cache_file in cache_dir.iterdir():
                if cache_file.is_file():
                    cache_file.unlink()
            try:
                cache_dir.rmdir()
            except OSError:
                pass
        try:
            output_dir.rmdir()
        except OSError:
            pass


@pytest.mark.skipif(importlib.util.find_spec("matplotlib") is None, reason="matplotlib optional rl extra is not installed")
def test_metric_plots_and_match_summary_plot():
    history = MetricHistory()
    comparison = MetricHistory()
    for step in range(3):
        history.log("loss", 1.0 / (step + 1), step=step, phase="train", run="supervised")
        history.log("accuracy", 0.5 + step * 0.1, step=step, phase="validation", run="supervised")
        comparison.log("loss", 1.2 / (step + 1), step=step, phase="train", run="baseline")

    output_dir = Path(".test-output")
    output_dir.mkdir(exist_ok=True)
    metric_path = output_dir / f"metrics-{uuid4().hex}.png"
    comparison_path = output_dir / f"comparison-{uuid4().hex}.png"
    matches_csv = output_dir / f"matches-{uuid4().hex}.csv"
    match_plot = output_dir / f"matches-{uuid4().hex}.png"
    try:
        save_metric_plot(history, metric_path, metrics=["loss", "accuracy"])
        save_comparison_plot({"candidate": history, "baseline": comparison}, comparison_path, metric="loss")
        matches_csv.write_text(
            "match_id,pairing_id,game,bot_a,bot_b,winner,winner_bot,reason,turns,a_remaining,b_remaining\n"
            "m1,,0,a,b,A,a,all ships sunk,60,10,9\n"
            "m2,,1,a,b,B,b,all ships sunk,70,8,11\n"
        )
        match_history = match_history_from_csv(matches_csv)
        save_match_summary_plot(matches_csv, match_plot)

        assert metric_path.exists()
        assert comparison_path.exists()
        assert match_plot.exists()
        assert match_history.values("turns", phase="match", run="matches") == [60.0, 70.0]
    finally:
        metric_path.unlink(missing_ok=True)
        comparison_path.unlink(missing_ok=True)
        matches_csv.unlink(missing_ok=True)
        match_plot.unlink(missing_ok=True)
        try:
            output_dir.rmdir()
        except OSError:
            pass


def test_possible_fleets_cover_unresolved_hits():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))

    fleets = possible_fleets(rules, state.snapshot(), max_fleets=5)

    assert fleets
    for fleet in fleets:
        engine = GameEngine(rules)
        engine.place_fleet(Player.A, list(fleet))
        assert (5, 5) in {cell for cells in engine.fleet_cells(Player.A).values() for cell in cells}


def test_sampled_occupancy_heatmap_is_not_row_major_biased_on_empty_board():
    rules = official_rules()
    state = ObservationState(rules)

    heat = occupancy_heatmap(rules, state.snapshot(), max_samples=300)

    top_edge = float(heat[0].mean())
    middle_rows = float(heat[4:6].mean())
    corners = float((heat[0, 0] + heat[0, -1] + heat[-1, 0] + heat[-1, -1]) / 4)
    center = float(heat[4:6, 4:6].mean())
    assert middle_rows > top_edge
    assert center > corners


def test_sample_possible_fleets_cover_unresolved_hits():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))

    fleets = sample_possible_fleets(rules, state.snapshot(), max_samples=10)

    assert fleets
    for fleet in fleets:
        assert (5, 5) in {cell for placement in fleet for cell in ship_cells(rules, placement)}


def test_sample_possible_fleets_cover_multiple_unresolved_hits():
    rules = official_rules()
    state = ObservationState(rules)
    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    state.apply_result(PublicShotResult((5, 6), Outcome.HIT))

    fleets = sample_possible_fleets(rules, state.snapshot(), max_samples=20)

    assert len(fleets) == 20
    for fleet in fleets:
        occupied = {cell for placement in fleet for cell in ship_cells(rules, placement)}
        assert {(5, 5), (5, 6)} <= occupied


def test_filter_refill_and_heatmap_helpers_form_incremental_pipeline():
    rules = official_rules()
    state = ObservationState(rules)
    fleets = sample_possible_fleets(rules, state.snapshot(), max_samples=20)

    state.apply_result(PublicShotResult((0, 0), Outcome.MISS))
    retained = filter_possible_fleets(rules, state.snapshot(), fleets)
    refilled, count = refill_possible_fleets(rules, state.snapshot(), retained, max_samples=20)
    heat = occupancy_from_fleets(rules, refilled)

    assert len(refilled) == len(retained) + count
    assert len(refilled) <= 20
    assert all((0, 0) not in {cell for placement in fleet for cell in ship_cells(rules, placement)} for fleet in refilled)
    assert heat.shape == (rules.rows, rules.cols)
    assert heat[0, 0] == 0.0


def test_sampling_helpers_treat_max_samples_as_ceiling_with_time_limit():
    rules = official_rules()
    state = ObservationState(rules)

    fleets = sample_possible_fleets(rules, state.snapshot(), max_samples=10, time_limit=0.0)
    refilled, count = refill_possible_fleets(rules, state.snapshot(), fleets, max_samples=10, time_limit=0.0)
    pool = FleetSamplePool(rules, max_samples=10, time_limit=0.0)
    pooled = pool.update(state.snapshot())

    assert fleets == []
    assert refilled == []
    assert count == 0
    assert pooled == []
    assert pool.shortfall == 10


def test_fleet_sample_pool_retains_and_refills_after_miss():
    rules = official_rules()
    state = ObservationState(rules)
    pool = FleetSamplePool(rules, max_samples=50)
    pool.update(state.snapshot())

    state.apply_result(PublicShotResult((0, 0), Outcome.MISS))
    fleets = pool.update(state.snapshot())

    assert len(fleets) == 50
    assert pool.retained <= 50
    assert pool.refilled == 50 - pool.retained
    assert all((0, 0) not in {cell for placement in fleet for cell in ship_cells(rules, placement)} for fleet in fleets)


def test_fleet_sample_pool_retains_only_fleets_that_cover_hits():
    rules = official_rules()
    state = ObservationState(rules)
    pool = FleetSamplePool(rules, max_samples=50)
    pool.update(state.snapshot())

    state.apply_result(PublicShotResult((5, 5), Outcome.HIT))
    fleets = pool.update(state.snapshot())

    assert len(fleets) == 50
    assert all((5, 5) in {cell for placement in fleet for cell in ship_cells(rules, placement)} for fleet in fleets)


def test_normalize_alive_fleet_drops_known_sunk_ship_when_it_matches_sunk_cells():
    rules = official_rules()
    state = ObservationState(rules)
    fleet = sample_possible_fleets(rules, state.snapshot(), max_samples=1)[0]
    sunk_placement = fleet[0]
    sunk_cells = ship_cells(rules, sunk_placement)
    state.apply_result(PublicShotResult(sunk_cells[0], Outcome.SUNK, SunkShip(sunk_placement.slot, sunk_cells)))

    normalized = normalize_alive_fleet(rules, state.snapshot(), fleet)

    assert normalized is not None
    assert sunk_placement.slot not in {placement.slot for placement in normalized}
    assert len(normalized) == len(fleet) - 1
