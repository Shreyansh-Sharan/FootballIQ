from footballiq.ml.retro import assign_folds, held_out


def test_folds_are_balanced_deterministic_and_disjoint():
    ids = [f"m{i}" for i in range(103)]
    a, b = assign_folds(ids, 4), assign_folds(reversed(ids), 4)
    assert a == b                                                   # order-independent
    sizes = [len(held_out(a, k)) for k in range(4)]
    assert sum(sizes) == 103 and max(sizes) - min(sizes) <= 1
    assert set().union(*(held_out(a, k) for k in range(4))) == set(ids)


def test_a_match_is_never_in_its_own_training_set():
    folds = assign_folds(["3869685", "3943043", "3857254", "3857255"], 2)
    for k in range(2):
        train = {m for m, f in folds.items() if f != k}
        assert not (train & held_out(folds, k))


def test_needs_two_folds():
    import pytest
    with pytest.raises(ValueError):
        assign_folds(["a", "b"], 1)
