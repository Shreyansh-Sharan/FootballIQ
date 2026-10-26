from footballiq.ml import motifs as MO


def test_triangle_context_and_persistence():
    team = [(50, 30), (60, 30), (55, 38), (20, 60)]            # a clear triangle + one isolated player
    opp = [(90, 10)]
    first = MO.sample(team, opp, ball=(50, 30), ids=["a", "b", "c", "d"])
    assert first["triangles"] == 1 and first["quads"] == 0
    tri = first["motifs"][0]
    assert tri["players"] == ["a", "b", "c"] and tri["persistence"] == 0 and 0 < tri["score"] <= 1
    again = MO.sample(team, opp, ball=(50, 30), ids=["a", "b", "c", "d"], previous=first["seen"])
    assert again["motifs"][0]["persistence"] == 1 and again["motifs"][0]["score"] > tri["score"]


def test_blocked_lane_breaks_the_motif():
    team = [(50, 30), (60, 30), (55, 38)]
    blocked = MO.sample(team, [(55, 30.5)], ball=(50, 30))     # opponent sits on the a-b lane
    assert blocked["triangles"] == 0
    pressed = MO.sample(team, [(55, 33)], ball=(50, 30))
    free = MO.sample(team, [(95, 60)], ball=(50, 30))
    if pressed["motifs"]:
        assert pressed["motifs"][0]["pressure_relief"] < free["motifs"][0]["pressure_relief"]
