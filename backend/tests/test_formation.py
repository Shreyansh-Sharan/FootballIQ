import numpy as np

from footballiq.ml import formation as FM


def _shape(name, seed=0, noise=1.0):
    rng = np.random.default_rng(seed)
    return [(30 + 25 * x + rng.normal(0, noise), 10 + 48 * y + rng.normal(0, noise)) for x, y in FM.FORMATIONS[name]]


def test_assign_recovers_templates_with_confidence():
    for name in FM.FORMATIONS:
        a = FM.assign(_shape(name))
        assert a.formation == name and 0 < a.confidence <= 1 and sorted(a.roles) == list(range(10))
    assert FM.assign(_shape("4-4-2")[:9]).formation is None


def test_hysteresis_ignores_single_noisy_segment():
    labels = ["4-4-2", "4-4-2", "4-3-3", "4-4-2", "5-4-1", "5-4-1", "5-4-1"]
    conf = [0.3] * len(labels)
    sm = FM.smooth(labels, conf, min_run=2)
    assert sm == ["4-4-2", "4-4-2", "4-4-2", "4-4-2", "4-4-2", "5-4-1", "5-4-1"]
    assert FM.switches(list(range(len(sm))), sm) == [(5, "4-4-2", "5-4-1")]
    assert FM.smooth(["4-3-3", "4-4-2"], [0.3, 0.01]) == ["4-3-3", "4-3-3"]   # low confidence never switches
