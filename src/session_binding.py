"""Bind one automation run to one browser page and one document/game identity."""

from dataclasses import dataclass
import uuid
from urllib.parse import urlsplit

from runtime_control import SessionChanged


def is_game_url(url):
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return host in ("wayground.com", "www.wayground.com", "quizizz.com", "www.quizizz.com") and (
        parts.path == "/join" or parts.path.startswith(("/join/", "/play/", "/game/"))
    )


def session_route(url):
    parts = urlsplit(url or "")
    return (parts.hostname or "").lower(), parts.path.rstrip("/")


def _route_token(route):
    """Opaque game tokens are identities, whereas lobby/assessment are stages."""
    reserved = {"join", "play", "game", "quiz", "assessment", "practice", "lobby",
                "pre-game", "waiting", "classic", "instructor-paced", "self-paced"}
    tokens = [part for part in route[1].split("/") if part and part not in reserved]
    return tokens[-1] if tokens else ""


def _lobby_route(route):
    return route[1] in ("/join", "/join/lobby", "/join/waiting", "/join/pre-game")


SESSION_INFO_SCRIPT = r"""
() => {
    const result = {pin: '', hash: '', pinSource: '', hashSource: '', quizId: '', marker: window.__wgAutomatorDocument || ''};
    const params = new URLSearchParams(location.search);
    result.pin = params.get('gc') || params.get('gameCode') || params.get('roomCode') || '';
    result.hash = params.get('roomHash') || '';
    if (result.pin) result.pinSource = 'url';
    if (result.hash) result.hashSource = 'url';
    const visible = document.body ? document.body.innerText : '';
    if (!result.pin) {
        const match = visible.match(/(?:Game\s*(?:Code|PIN)|Код\s*(?:гри|игры)|PIN)\s*[:#]?\s*(\d{4,9})/i);
        if (match) { result.pin = match[1]; result.pinSource = 'visible'; }
    }
    // Session storage is scoped to this tab; shared localStorage is not an identity.
    try {
        for (let i = 0; i < sessionStorage.length; i++) {
            const name = sessionStorage.key(i) || '';
            const value = sessionStorage.getItem(name) || '';
            if (value.length > 500000) continue;
            if (!result.pin && /^(gc|pin|roomCode|gameCode)$/i.test(name) && /^\d{4,9}$/.test(value)) {
                result.pin = value; result.pinSource = 'storage';
            }
            if (!result.hash) {
                const match = value.match(/["']roomHash["']\s*:\s*["']([a-zA-Z0-9_-]{10,})["']/);
                if (match) { result.hash = match[1]; result.hashSource = 'storage'; }
            }
        }
    } catch (_) {}
    if (!result.pin && document.referrer) {
        const match = document.referrer.match(/[?&]gc=(\d{4,9})/);
        if (match) { result.pin = match[1]; result.pinSource = 'referrer'; }
    }
    return result;
}
"""


@dataclass
class SessionBinding:
    page: object
    pin: str
    room_hash: str
    route: tuple
    marker: str

    @classmethod
    async def create(cls, page, *, pin="", room_hash=""):
        marker = uuid.uuid4().hex
        await page.evaluate("(token) => { window.__wgAutomatorDocument = token; }", marker)
        return cls(page, str(pin or ""), str(room_hash or ""), session_route(page.url), marker)

    async def validate(self, *, captured=None):
        if self.page.is_closed():
            raise SessionChanged("The selected test tab was closed. Select and prepare a test again.")
        url = self.page.url or ""
        parts = urlsplit(url)
        if (parts.hostname or "").lower() != self.route[0]:
            raise SessionChanged("The selected tab left Wayground. Prepare a test again.")
        results = any(part in parts.path.lower() for part in ("/game-summary", "/results", "/summary", "/report"))
        if not is_game_url(url) and not results:
            raise SessionChanged("The selected tab left the game. Select and prepare a test again.")
        info = await self.page.evaluate(SESSION_INFO_SCRIPT) or {}
        pin = str(info.get("pin") or "")
        room_hash = str(info.get("hash") or "")
        # Referrers and stored values can describe a game previously played in
        # this tab. They help discovery, but cannot authorize a changed route.
        trusted_pin = pin if info.get("pinSource") not in ("storage", "referrer") else ""
        trusted_hash = room_hash if info.get("hashSource") != "storage" else ""
        captured = captured or {}
        if captured.get("pin"):
            if trusted_pin and trusted_pin != str(captured["pin"]):
                raise SessionChanged("The game PIN changed. Select and prepare this new game.")
            trusted_pin = str(captured["pin"])
        if captured.get("hash"):
            if trusted_hash and trusted_hash != str(captured["hash"]):
                raise SessionChanged("The game session changed. Select and prepare this new game.")
            trusted_hash = str(captured["hash"])
        if trusted_pin and self.pin and trusted_pin != self.pin:
            raise SessionChanged("The game PIN changed. Select and prepare this new game.")
        if trusted_hash and self.room_hash and trusted_hash != self.room_hash:
            raise SessionChanged("The game session changed. Select and prepare this new game.")
        if not self.pin and trusted_pin:
            self.pin = trusted_pin
        if not self.room_hash and trusted_hash:
            self.room_hash = trusted_hash
        current = session_route(url)
        old_token, current_token = _route_token(self.route), _route_token(current)
        if not results and old_token and current_token and old_token != current_token:
            raise SessionChanged("The selected tab switched games. Refresh tabs and prepare the new test.")
        same_identity = bool((trusted_pin and self.pin and trusted_pin == self.pin) or
                             (trusted_hash and self.room_hash and trusted_hash == self.room_hash) or
                             (old_token and current_token == old_token))
        same_document = info.get("marker") == self.marker
        if not results and not same_document:
            # Joining from the PIN lobby may load the actual game document.
            # A generic reload or navigation between active tests still stops.
            lobby_entered = _lobby_route(self.route) and current != self.route and same_identity
            if not lobby_entered:
                raise SessionChanged("The game page was reloaded. Refresh tabs and prepare its answers again.")
            await self.page.evaluate("(token) => { window.__wgAutomatorDocument = token; }", self.marker)
        if not results and current != self.route:
            if not same_identity:
                raise SessionChanged("The selected tab switched games. Refresh tabs and prepare the new test.")
            self.route = current
