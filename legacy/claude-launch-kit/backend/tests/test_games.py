import random
from app.games import HandCricket, LastCard, BOT


def test_hand_cricket_full_game_two_humans():
    g = HandCricket(1, 2)
    g.move(1, {"n": 4}); assert g.view(1)["waiting"] and g.score[1] == 0
    g.move(2, {"n": 2}); assert g.score[1] == 4
    g.move(1, {"n": 3}); g.move(2, {"n": 3})           # out
    assert g.innings == 2 and g.target == 5 and g.batting == 2
    g.move(2, {"n": 6}); g.move(1, {"n": 1})           # 2 chases 5 with a six
    assert g.over and g.winner == 2


def test_hand_cricket_vs_mindy_always_finishes():
    for seed in range(30):
        g = HandCricket(7, BOT, rng=random.Random(seed))
        for _ in range(500):
            if g.over:
                break
            assert g.move(7, {"n": random.Random(seed).randint(1, 6)}) is None
        assert g.over


def test_last_card_rules_and_bots():
    rng = random.Random(3)
    g = LastCard([5, BOT], rng=rng, names={5: "Aanya"})
    assert len(g.hands[5]) == 7 and g.current() == 5
    assert g.move(BOT, {"act": "draw"}) == "not your turn"
    bad = next((c for c in g.hands[5] if not g.playable(c)), None)
    if bad:
        assert g.move(5, {"act": "play", "card": bad["id"]}) == "that card doesn't match"
    # play until someone wins: always play the first playable card, else draw
    for _ in range(2000):
        if g.over:
            break
        hand = g.hands[5]
        c = next((c for c in hand if g.playable(c)), None)
        g.move(5, {"act": "play", "card": c["id"], "colour": "cyan", "last": True} if c else {"act": "draw"})
    assert g.over and g.winner in (5, BOT)


def test_last_card_penalty_for_not_saying_it():
    g = LastCard([1, 2], rng=random.Random(1))
    g.hands[1] = [{"c": g.colour, "v": "5", "id": 900}, {"c": g.colour, "v": "6", "id": 901}]
    g.move(1, {"act": "play", "card": 900})             # down to one card, didn't say it
    assert len(g.hands[1]) == 3


def test_last_card_plus_two():
    g = LastCard([1, 2, 3], rng=random.Random(2))
    g.hands[1] = [{"c": g.colour, "v": "+2", "id": 900}, {"c": "pink", "v": "1", "id": 901}, {"c": "pink", "v": "2", "id": 902}]
    before = len(g.hands[2])
    g.move(1, {"act": "play", "card": 900})
    assert len(g.hands[2]) == before + 2 and g.current() == 3
