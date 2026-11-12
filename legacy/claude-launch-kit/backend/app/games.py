"""Game engines. Pure logic, no networking: the server holds the truth and sends each player their own view.
BOT is Mindy, so anyone can play alone."""
import random

BOT = 0  # user id 0 = Mindy


class HandCricket:
    """Odd-even hand cricket. Both throw 1-6 at the same time. Same number: the batter is out.
    Otherwise the batter scores their own number. Two innings; the second chases the first's total."""
    kind = "hand"

    def __init__(self, a: int, b: int, rng: random.Random | None = None):
        self.players = [a, b]
        self.rng = rng or random.Random()
        self.batting = a
        self.score = {a: 0, b: 0}
        self.innings = 1
        self.target = None
        self.throws: dict[int, int] = {}
        self.last = None
        self.winner = None
        self.over = False
        self.log: list[str] = []

    def bowler(self):
        return self.players[1] if self.batting == self.players[0] else self.players[0]

    def move(self, pid: int, data: dict):
        if self.over or pid not in self.players:
            return "game over" if self.over else "not your game"
        n = int(data.get("n", 0))
        if not 1 <= n <= 6:
            return "pick a number from 1 to 6"
        self.throws[pid] = n
        if BOT in self.players and BOT not in self.throws:
            self.throws[BOT] = self.rng.randint(1, 6)
        if len(self.throws) < 2:
            return None
        bat, bowl = self.batting, self.bowler()
        tb, tw = self.throws[bat], self.throws[bowl]
        self.throws = {}
        if tb == tw:
            self.last = {"bat": tb, "bowl": tw, "out": True, "runs": 0}
            self.log.append(f"OUT! Both threw {tb}.")
            if self.innings == 1:
                self.innings, self.target, self.batting = 2, self.score[bat] + 1, bowl
            else:
                self._finish()
        else:
            self.score[bat] += tb
            self.last = {"bat": tb, "bowl": tw, "out": False, "runs": tb}
            self.log.append(f"+{tb}")
            if self.innings == 2 and self.score[bat] >= self.target:
                self._finish()
        return None

    def _finish(self):
        a, b = self.players
        self.over = True
        self.winner = a if self.score[a] > self.score[b] else b if self.score[b] > self.score[a] else None

    def view(self, pid: int) -> dict:
        return {"kind": self.kind, "players": self.players, "batting": self.batting, "score": {str(k): v for k, v in self.score.items()},
                "innings": self.innings, "target": self.target, "waiting": pid in self.throws, "last": self.last,
                "over": self.over, "winner": self.winner, "log": self.log[-6:]}


COLOURS = ["cyan", "pink", "mint", "violet"]


class LastCard:
    """A colour-and-number shedding game for 2-4. Match the top card's colour or value, or play a wild.
    +2 makes the next player draw two and miss their go; skip skips; reverse turns it round (with two players it acts as skip).
    Going down to one card without saying "last card" costs two cards. First to empty their hand wins."""
    kind = "lastcard"

    def __init__(self, players: list[int], rng: random.Random | None = None, names: dict | None = None):
        self.rng = rng or random.Random()
        self.names = names or {}
        self.players = list(players)
        deck = []
        for c in COLOURS:
            deck.append({"c": c, "v": "0"})
            for v in [str(i) for i in range(1, 10)] + ["+2", "skip", "rev"]:
                deck += [{"c": c, "v": v}, {"c": c, "v": v}]
        deck += [{"c": "wild", "v": "wild"} for _ in range(4)]
        self.rng.shuffle(deck)
        for i, card in enumerate(deck):
            card["id"] = i
        self.deck = deck
        self.discard = []
        self.hands = {p: [self.deck.pop() for _ in range(7)] for p in self.players}
        top = self.deck.pop()
        while top["c"] == "wild" or not top["v"].isdigit():
            self.deck.insert(0, top)
            top = self.deck.pop()
        self.discard.append(top)
        self.colour = top["c"]
        self.turn = 0
        self.dir = 1
        self.winner = None
        self.over = False
        self.log = [f"Game on. Top card: {top['c']} {top['v']}."]
        self._bots()

    @property
    def top(self):
        return self.discard[-1]

    def current(self):
        return self.players[self.turn]

    def _next(self, steps=1):
        self.turn = (self.turn + self.dir * steps) % len(self.players)

    def _draw(self, pid, n):
        for _ in range(n):
            if not self.deck:
                keep = self.discard.pop()
                self.deck, self.discard = self.discard, [keep]
                self.rng.shuffle(self.deck)
            if self.deck:
                self.hands[pid].append(self.deck.pop())

    def playable(self, card):
        return card["c"] == "wild" or card["c"] == self.colour or card["v"] == self.top["v"]

    def move(self, pid: int, data: dict):
        if self.over:
            return "game over"
        if pid != self.current():
            return "not your turn"
        act = data.get("act")
        if act == "draw":
            self._draw(pid, 1)
            self.log.append(f"{self._n(pid)} drew a card.")
            self._next()
        elif act == "play":
            card = next((c for c in self.hands[pid] if c["id"] == data.get("card")), None)
            if not card:
                return "you don't have that card"
            if not self.playable(card):
                return "that card doesn't match"
            self.hands[pid].remove(card)
            self.discard.append(card)
            self.colour = data.get("colour") if card["c"] == "wild" and data.get("colour") in COLOURS else (self.rng.choice(COLOURS) if card["c"] == "wild" else card["c"])
            self.log.append(f"{self._n(pid)} played {card['c']} {card['v']}" + (f", chose {self.colour}" if card["c"] == "wild" else "") + ".")
            if not self.hands[pid]:
                self.over, self.winner = True, pid
                self.log.append(f"{self._n(pid)} wins!")
                return None
            if len(self.hands[pid]) == 1 and not data.get("last"):
                self._draw(pid, 2)
                self.log.append(f"{self._n(pid)} forgot to say “last card”. Draw two!")
            two = len(self.players) == 2
            if card["v"] == "+2":
                self._next()
                self._draw(self.current(), 2)
                self.log.append(f"{self._n(self.current())} draws two and misses a go.")
                self._next()
            elif card["v"] == "skip" or (card["v"] == "rev" and two):
                self._next(2)
            elif card["v"] == "rev":
                self.dir *= -1
                self._next()
            else:
                self._next()
        else:
            return "unknown move"
        self._bots()
        return None

    def _bots(self):
        guard = 0
        while not self.over and self.current() == BOT and guard < 20:
            guard += 1
            hand = self.hands[BOT]
            card = next((c for c in hand if self.playable(c) and c["c"] != "wild"), None) or next((c for c in hand if self.playable(c)), None)
            if card:
                counts = {c: sum(1 for h in hand if h["c"] == c) for c in COLOURS}
                self.move(BOT, {"act": "play", "card": card["id"], "colour": max(counts, key=counts.get), "last": True})
            else:
                self.move(BOT, {"act": "draw"})

    def _n(self, pid):
        return "Mindy" if pid == BOT else self.names.get(pid, "Someone")

    def view(self, pid: int) -> dict:
        return {"kind": self.kind, "players": self.players, "turn": self.current(), "you": pid, "top": self.top, "colour": self.colour,
                "hand": self.hands.get(pid, []), "counts": {str(p): len(h) for p, h in self.hands.items()},
                "over": self.over, "winner": self.winner, "log": self.log[-5:], "deck": len(self.deck)}
