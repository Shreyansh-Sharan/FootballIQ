from footballiq.ingest.statsbomb import clock_label, normalize_match, parse_timestamp_ms
from footballiq.pitch import statsbomb_to_canonical


def test_parse_timestamp():
    assert parse_timestamp_ms("00:52:34.569") == 3_154_569


def test_clock_label_handles_stoppage_and_shootout():
    assert clock_label(1, 22 * 60_000 + 24_000) == "22:24"
    assert clock_label(2, 0) == "45:00"
    assert clock_label(1, 52 * 60_000 + 34_000) == "45+07:34"
    assert clock_label(4, 16 * 60_000) == "120+01:00"
    assert clock_label(5, 1000) == "PEN"


def test_pitch_transform_flips_away_team():
    assert statsbomb_to_canonical([120, 80], True) == (105.0, 68.0)
    assert statsbomb_to_canonical([120, 80], False) == (0.0, 0.0)
    assert statsbomb_to_canonical(None, True) is None


def test_normalize_builds_monotonic_canonical_clock(raw_match):
    match, events, frames = normalize_match(raw_match, 99)
    assert match.canonical_match_id == "2022-01-01_home-fc_away-fc"
    assert [p.duration_ms for p in match.periods] == [45 * 60_000, 46 * 60_000]
    assert match.periods[1].start_match_ms == 45 * 60_000
    times = [e.match_elapsed_ms for e in events]
    assert times == sorted(times)
    shot2 = next(e for e in events if e.event_id == "e7")
    assert shot2.match_elapsed_ms == 65 * 60_000
    assert shot2.is_goal and shot2.subtype == "Penalty"
    # away team event mirrored into home-attacks-right frame
    assert shot2.x_m == round(105 - 110 * 105 / 120, 2)


def test_implicit_pass_outcome_and_freeze_frame(raw_match):
    _, events, frames = normalize_match(raw_match, 99)
    assert next(e for e in events if e.event_id == "e2").outcome == "Complete"
    assert next(e for e in events if e.event_id == "e3").outcome == "Incomplete"
    assert len(frames) == 1 and frames[0].event_id == "e4"
    keeper = next(p for p in frames[0].players if p.keeper)
    assert keeper.team_id == "away-fc" and not keeper.teammate
