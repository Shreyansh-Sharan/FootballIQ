import math

from footballiq.ml import xpass_tracking as XT


def _f(**kw):
    base = dict(attack_right=True, height="G", body="R", setpiece="O", is_cross=False, target_speed=3.0,
                passer_observed=True, target_observed=None, opps_observed=[True, False])
    base.update(kw)
    return XT.features((50, 34), (70, 34), [(60, 20)], [(60, 34.5), (80, 50)], **base)


def test_lane_pressure_and_space():
    f = _f()
    assert f["length_m"] == 20 and f["forward_ratio"] == 1.0
    assert f["lane_within_1_5m"] == 1 and math.isclose(f["lane_min_dist_m"], 0.5)
    assert math.isclose(f["press_nearest_m"], math.hypot(10, 0.5))
    assert f["opps_goal_side_of_target"] == 1 and f["target_mates_within_10m"] == 0
    assert f["height_ground"] == 1 and f["body_right_foot"] == 1 and f["sp_open_play"] == 1
    assert math.isnan(f["target_observed"]) and f["opps_observed_share"] == 0.5   # unknown stays unknown


def test_away_team_is_flipped_into_its_attacking_frame():
    home = _f()
    away = XT.features((105 - 50, 68 - 34), (105 - 70, 68 - 34), [(105 - 60, 68 - 20)], [(105 - 60, 68 - 34.5), (105 - 80, 68 - 50)],
                       attack_right=False, height="G", body="R", setpiece="O", is_cross=False, target_speed=3.0,
                       passer_observed=True, target_observed=None, opps_observed=[True, False])
    for k in ("x", "tx", "dx", "progress_m", "lane_min_dist_m", "opps_goal_side_of_target"):
        assert math.isclose(home[k], away[k], abs_tol=1e-9), k
    assert set(XT.EVENT_FEATURES) | set(XT.TRACKING_FEATURES) <= set(home)
