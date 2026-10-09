"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/prng.py."""
from __future__ import annotations

from arc_agent.prng import create_seeded_random, generate_seed


def test_create_seeded_random_is_deterministic_for_same_seed() -> None:
    rng_a = create_seeded_random("same-seed")
    rng_b = create_seeded_random("same-seed")
    assert [rng_a() for _ in range(10)] == [rng_b() for _ in range(10)]


def test_create_seeded_random_differs_across_seeds() -> None:
    rng_a = create_seeded_random("seed-a")
    rng_b = create_seeded_random("seed-b")
    assert [rng_a() for _ in range(5)] != [rng_b() for _ in range(5)]


def test_create_seeded_random_values_in_unit_interval() -> None:
    rng = create_seeded_random("range-test")
    values = [rng() for _ in range(200)]
    assert all(0.0 <= v < 1.0 for v in values)


def test_generate_seed_is_non_deterministic_and_non_empty() -> None:
    seed_a = generate_seed()
    seed_b = generate_seed()
    assert seed_a and seed_b
    assert seed_a != seed_b
