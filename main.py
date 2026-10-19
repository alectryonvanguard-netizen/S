# main.py - My Store with accounts, terms/policy screen and Settings.
# The server address is fixed (SERVER below); users cannot change it.
import os
import ssl
import math
import time
import json
import uuid
import hashlib
import threading
import traceback
from urllib.request import urlopen, Request
from urllib.parse import quote, urlparse, parse_qs
from urllib.error import HTTPError

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup as esc

# Android has no built-in list of trusted certificates, so use certifi's.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    CERT_SOURCE = "certifi"
except Exception:
    SSL_CTX = ssl.create_default_context()
    CERT_SOURCE = "built-in (certifi missing)"

try:
    from store_notify import is_newer, read_inbox, clear_inbox, KINDS
except Exception:                                   # keeps the app starting even if the file is missing
    KINDS = {"new": "New app", "update": "App update", "self": "My Store update", "test": "Test"}

    def read_inbox():
        return []

    def clear_inbox():
        pass

    def is_newer(new, old):
        return False

SERVER = "https://sam202411.pythonanywhere.com"
APP_VERSION = "1.0"
TERMS_VERSION = "2026-10"
SESSION_EXPIRED = "Session expired"
SPLASH_SECONDS = 5     # how long the loading screen stays
HOME_LOGO = "logo_s.png"     # the colourful S ("logo_m.png" gives the M instead)
HIDE_PUBLISH_REQUEST = True   # True: "Publish an app" stays hidden until Version is tapped 7 times

# ---------------------------------------------------------------- colors
HEADER = (0.00, 0.55, 0.42, 1)
ACCENT = (0.00, 0.62, 0.45, 1)
PAGE = (0.95, 0.96, 0.98, 1)
WHITE = (1, 1, 1, 1)
DARK = (0.12, 0.13, 0.17, 1)
GRAY = (0.45, 0.47, 0.53, 1)
RED = (0.88, 0.22, 0.20, 1)
CHIP_BG = (0.88, 0.90, 0.94, 1)
ICON_COLORS = [
    (0.26, 0.52, 0.96, 1), (0.92, 0.26, 0.21, 1), (0.98, 0.74, 0.02, 1),
    (0.20, 0.66, 0.33, 1), (0.61, 0.15, 0.69, 1), (1.00, 0.34, 0.13, 1),
    (0.00, 0.74, 0.83, 1), (0.91, 0.12, 0.39, 1),
]

# ---------------------------------------------------------------- policies (edit to match your store)
POLICIES = [
    ("tos", "Terms of Service",
     "My Store lets you browse and install apps from independent developers and from "
     "other open sources. Apps are provided as-is and you are responsible for what you "
     "install. Do not upload apps you have no right to distribute, or apps that contain "
     "malware, spyware or hidden charges. Accounts that break these rules can be removed."),
    ("privacy", "Privacy Policy",
     "We store your email, display name, a hashed password and an anonymous device ID. "
     "They are used to run your account and to stop fake verification votes. Your "
     "downloads and votes are tied to your account. We do not sell your data. You can "
     "delete your account and its votes any time in Settings > Delete account."),
    ("content", "Content & Mod Policy",
     "Verified means several different users installed the app, the file matched its "
     "published checksum, and they said it worked. It is NOT a security audit. Mods are "
     "unofficial changes made by third parties; they can break apps, break the original "
     "app's rules, or contain malware. Apps that many users report are hidden. Install "
     "only what you trust."),
]

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except Exception:
    HERE = "."
PREFS_PATH = os.path.join(HERE, "store_prefs.json")


# ---------------------------------------------------------------- saved settings
def default_prefs():
    return {"server": SERVER, "accounts": [], "active": "", "accepted": {},
            "warn_unverified": True, "ask_verify": True, "show_mods": True,
            "show_external": True, "sort": "popular", "downloads": [],
            "dev_unlocked": False, "guest": False,
            "tracked": {}, "notify_updates": True, "perm_asked": False}


def load_prefs():
    p = default_prefs()
    try:
        with open(PREFS_PATH) as f:
            p.update(json.load(f))
    except Exception:
        pass
    p["server"] = SERVER      # always use the fixed server, even if an old one was saved
    return p


def save_prefs():
    try:
        with open(PREFS_PATH, "w") as f:
            json.dump(P, f)
    except Exception:
        pass


P = load_prefs()


# ---------------------------------------------------------------- network (no Kivy)
def call(path, payload=None, token=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(SERVER + path, data=data, headers=headers),
                     timeout=20, context=SSL_CTX) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        msg = None
        try:
            msg = json.loads(e.read().decode()).get("error")
        except Exception:
            pass
        raise Exception(msg or "Server error %d" % e.code)


def fetch_file(url, path, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    h = hashlib.sha256()
    with urlopen(Request(url, headers=headers), timeout=60, context=SSL_CTX) as r, \
            open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
    return h.hexdigest()


def run_bg(work, done):
    def runner():
        result, error = None, None
        try:
            result = work()
        except Exception as e:
            error = str(e)
        Clock.schedule_once(lambda dt: done(result, error))
    threading.Thread(target=runner, daemon=True).start()


def device_id():
    p = os.path.join(HERE, "device.id")
    try:
        if os.path.exists(p):
            return open(p).read().strip()
        d = uuid.uuid4().hex
        open(p, "w").write(d)
        return d
    except Exception:
        return uuid.uuid4().hex


def save_dir():
    d = "/storage/emulated/0/Download"
    try:
        t = os.path.join(d, ".w")
        open(t, "w").write("x")
        os.remove(t)
        return d
    except Exception:
        return HERE


# ---------------------------------------------------------------- ui helpers
def paint(w, rgba, radius=14):
    """Rounded background. If graphics ever fails it is skipped, never crashes."""
    try:
        from kivy.graphics import Color, RoundedRectangle
        rad = [dp(x) for x in radius] if isinstance(radius, (list, tuple)) else [dp(radius)]
        with w.canvas.before:
            Color(*rgba)
            r = RoundedRectangle(pos=w.pos, size=w.size, radius=rad)
        w.bind(pos=lambda i, v: setattr(r, "pos", v),
               size=lambda i, v: setattr(r, "size", v))
    except Exception:
        pass


def text(txt, size="14sp", color=DARK, bold=False, height=None, shorten=False, halign="left"):
    lbl = Label(text=txt, markup=True, halign=halign, valign="middle",
                font_size=size, color=color, bold=bold)
    if shorten:
        lbl.shorten = True
        lbl.shorten_from = "right"
    lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0], v[1])))
    if height:
        lbl.size_hint_y = None
        lbl.height = height
    return lbl


def auto_text(txt, size="13sp", color=DARK):
    """Wrapping label that grows to fit its text."""
    lbl = Label(text=txt, markup=True, halign="left", valign="top",
                font_size=size, color=color, size_hint_y=None)
    lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    lbl.bind(texture_size=lambda i, s: setattr(i, "height", s[1]))
    return lbl


def pill(label, bg, fg, h=38, size="13sp", bold=True):
    b = Button(text=label, size_hint_y=None, height=dp(h), background_normal="",
               background_down="", background_color=(0, 0, 0, 0), color=fg,
               font_size=size, bold=bold)
    paint(b, bg, radius=h / 2)
    return b


def field(hint, password=False, default=""):
    box = BoxLayout(size_hint_y=None, height=dp(50))
    paint(box, WHITE, 14)
    ti = TextInput(text=default, hint_text=hint, multiline=False, password=password,
                   background_normal="", background_active="", background_color=(0, 0, 0, 0),
                   foreground_color=DARK, hint_text_color=(0.55, 0.57, 0.62, 1),
                   cursor_color=ACCENT, padding=[dp(16), dp(15), dp(16), dp(10)])
    box.add_widget(ti)
    return box, ti


def area(hint, h=110):
    box = BoxLayout(size_hint_y=None, height=dp(h))
    paint(box, WHITE, 14)
    ti = TextInput(hint_text=hint, multiline=True, background_normal="", background_active="",
                   background_color=(0, 0, 0, 0), foreground_color=DARK,
                   hint_text_color=(0.55, 0.57, 0.62, 1), cursor_color=ACCENT,
                   padding=[dp(16), dp(14), dp(16), dp(10)])
    box.add_widget(ti)
    return box, ti


def avatar(name, size, bg=WHITE, fg=ACCENT):
    holder = AnchorLayout(size_hint=(None, None), size=(dp(size), dp(size)))
    tile = BoxLayout(size_hint=(None, None), size=(dp(size), dp(size)))
    paint(tile, bg, size / 2)
    tile.add_widget(text("[b]%s[/b]" % esc((name or "?")[:1].upper()),
                         size="%dsp" % int(size * 0.45), color=fg, halign="center"))
    holder.add_widget(tile)
    return holder


# ---------------------------------------------------------------- dark theme (main shell)
NAVY = (0.027, 0.035, 0.094, 1)
NAV_BG = (0.043, 0.059, 0.153, 1)
CARD_D = (0.063, 0.082, 0.188, 1)
LINE_D = (0.12, 0.155, 0.33, 1)
TXT = (0.94, 0.96, 1.0, 1)
SUB = (0.58, 0.63, 0.80, 1)
CYAN = (0.13, 0.83, 0.93, 1)
VIOLET = (0.66, 0.33, 0.97, 1)
ORANGE = (1.0, 0.55, 0.15, 1)
CHIP_ON = (0.05, 0.27, 0.37, 1)
TAG_BG = (0.50, 0.22, 0.85, 1)
BANNER_BG = (0.10, 0.08, 0.35, 1)
BLUE_A = (0.0, 0.62, 0.96, 1)
BLUE_B = (0.25, 0.35, 0.96, 1)
CYAN_A = (0.0, 0.85, 0.95, 1)
CYAN_B = (0.10, 0.45, 0.95, 1)
GAME_WORDS = ("game", "action", "adventure", "racing", "puzzle", "arcade", "strategy", "rpg",
              "simulation", "shooter")


def ago(ts):
    s = max(0, int(time.time() - ts))
    if s < 60:
        return "just now"
    if s < 3600:
        return "%d min ago" % (s // 60)
    if s < 86400:
        return "%d h ago" % (s // 3600)
    return "%d days ago" % (s // 86400)


def vscroll(**kw):
    """Vertical scroller that follows the finger easily and leaves sideways swipes to the rows."""
    return ScrollView(bar_width=dp(3), scroll_type=["bars", "content"], scroll_distance=dp(10),
                      scroll_timeout=120, do_scroll_x=False, **kw)


class Dialog(ModalView):
    """Rounded dark card with a coloured title line. Used instead of the plain Kivy Popup."""

    def __init__(self, title="", content=None, size_hint=(0.9, None), **kw):
        kw.pop("separator_height", None)           # old Popup argument
        super().__init__(size_hint=size_hint, background="", background_color=(0, 0, 0, 0),
                         overlay_color=(0, 0, 0, 0.65), **kw)
        self.title, self.content = title, content
        card = BoxLayout(orientation="vertical", padding=[dp(18), dp(16), dp(18), dp(16)], spacing=dp(10))
        paint(card, CARD_D, 22)
        if title:
            card.add_widget(text("[b]%s[/b]" % esc(title), size="18sp", color=TXT, height=dp(30)))
            line = Widget(size_hint_y=None, height=dp(3))
            paint_grad(line, CYAN_A, VIOLET, 2)
            card.add_widget(line)
        if content is not None:
            card.add_widget(content)
        self.add_widget(card)


# brand-coloured tiles shown until (or instead of) a real icon picture
BRAND = (
    ("whatsapp", (0.15, 0.83, 0.40), WHITE), ("tiktok", (0.04, 0.04, 0.06), (0.15, 0.95, 0.93, 1)),
    ("instagram", (0.83, 0.20, 0.50), WHITE), ("spotify", (0.11, 0.73, 0.33), WHITE),
    ("youtube", (0.92, 0.07, 0.07), WHITE), ("facebook", (0.09, 0.47, 0.95), WHITE),
    ("messenger", (0.0, 0.52, 1.0), WHITE), ("telegram", (0.16, 0.64, 0.90), WHITE),
    ("snapchat", (1.0, 0.95, 0.0), (0.1, 0.1, 0.1, 1)), ("netflix", (0.06, 0.06, 0.06), (0.9, 0.05, 0.08, 1)),
    ("discord", (0.35, 0.40, 0.95), WHITE), ("linkedin", (0.04, 0.40, 0.76), WHITE),
    ("pinterest", (0.90, 0.0, 0.14), WHITE), ("reddit", (1.0, 0.27, 0.0), WHITE),
    ("twitch", (0.57, 0.27, 1.0), WHITE), ("zoom", (0.18, 0.55, 1.0), WHITE),
    ("minecraft", (0.38, 0.62, 0.22), WHITE), ("roblox", (0.90, 0.10, 0.10), WHITE),
    ("free fire", (1.0, 0.55, 0.0), WHITE), ("call of duty", (0.15, 0.17, 0.15), WHITE),
    ("pubg", (0.90, 0.55, 0.10), WHITE), ("genshin", (0.30, 0.55, 0.95), WHITE),
    ("clash", (0.95, 0.60, 0.10), WHITE), ("candy", (0.95, 0.35, 0.65), WHITE),
    ("uber", (0.05, 0.05, 0.05), WHITE), ("bolt", (0.20, 0.80, 0.45), WHITE),
    ("amazon", (1.0, 0.60, 0.0), (0.1, 0.1, 0.1, 1)), ("temu", (1.0, 0.45, 0.10), WHITE),
    ("duolingo", (0.35, 0.80, 0.0), WHITE), ("canva", (0.0, 0.76, 0.80), WHITE),
    ("capcut", (0.05, 0.05, 0.05), WHITE), ("paypal", (0.0, 0.19, 0.53), WHITE),
    ("signal", (0.23, 0.46, 0.96), WHITE), ("viber", (0.45, 0.30, 0.78), WHITE),
    ("skype", (0.0, 0.69, 0.94), WHITE), ("disney", (0.07, 0.12, 0.40), WHITE),
    ("wattpad", (1.0, 0.45, 0.0), WHITE), ("webtoon", (0.0, 0.78, 0.35), WHITE),
    ("kindle", (0.10, 0.45, 0.80), WHITE), ("gmail", (0.86, 0.22, 0.17), WHITE),
)


def brand(name):
    """(background, letter colour) for an app tile."""
    n = (name or "").lower().strip()
    if n in ("x", "x (twitter)", "twitter"):
        return (0.05, 0.05, 0.05, 1), WHITE
    for key, bg, fg in BRAND:
        if key in n:
            return tuple(bg) + (1,), fg
    return ICON_COLORS[sum(ord(c) for c in n) % len(ICON_COLORS)], WHITE


ICON_SLOTS = threading.Semaphore(4)           # at most 4 icon downloads at once
ICON_DIR = os.path.join(HERE, "icons_cache")


def cached_icon(url):
    base = os.path.join(ICON_DIR, hashlib.sha1(url.encode()).hexdigest())
    for ext in ("png", "jpg", "webp"):
        if os.path.exists(base + "." + ext):
            return base + "." + ext
    return None


def fetch_icon(url):
    """Download an icon picture once and keep it on the phone."""
    found = cached_icon(url)
    if found:
        return found
    with ICON_SLOTS:
        with urlopen(Request(url, headers={"User-Agent": "MyStore"}), timeout=15, context=SSL_CTX) as r:
            data = r.read(400 * 1024 + 1)
    if len(data) > 400 * 1024:
        raise Exception("icon too big")
    if data.startswith(b"\x89PNG"):
        ext = "png"
    elif data[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise Exception("not a picture")
    os.makedirs(ICON_DIR, exist_ok=True)
    path = os.path.join(ICON_DIR, hashlib.sha1(url.encode()).hexdigest() + "." + ext)
    with open(path, "wb") as f:
        f.write(data)
    return path


class RoundedIcon(Widget):
    """A picture drawn with rounded corners."""

    def __init__(self, path, corner=14, **kw):
        super().__init__(**kw)
        from kivy.core.image import Image as CoreImage
        self.tex = CoreImage(path, ext=path.rsplit(".", 1)[-1]).texture
        self.corner = corner
        self.bind(pos=self.redraw, size=self.redraw)

    def redraw(self, *a):
        from kivy.graphics import Color, RoundedRectangle
        self.canvas.clear()
        with self.canvas:
            Color(1, 1, 1, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(self.corner)], texture=self.tex)


class TapBox(ButtonBehavior, BoxLayout):
    """A layout you can tap."""


def paint_grad(w, c1, c2, radius=14):
    """Rounded background with a left-to-right colour fade (falls back to a flat colour)."""
    try:
        from kivy.graphics import Color, RoundedRectangle
        tex = gradient_texture(tuple(int(x * 255) for x in c1[:3]), tuple(int(x * 255) for x in c2[:3]))
        rad = [dp(x) for x in radius] if isinstance(radius, (list, tuple)) else [dp(radius)]
        with w.canvas.before:
            Color(1, 1, 1, 1)
            r = RoundedRectangle(pos=w.pos, size=w.size, radius=rad, texture=tex)
        w.bind(pos=lambda i, v: setattr(r, "pos", v), size=lambda i, v: setattr(r, "size", v))
    except Exception:
        paint(w, c1, radius)


def gpill(label, c1, c2, h=36, size="13sp"):
    b = Button(text=label, size_hint_y=None, height=dp(h), background_normal="",
               background_down="", background_color=(0, 0, 0, 0), color=WHITE,
               font_size=size, bold=True)
    paint_grad(b, c1, c2, radius=h / 2)
    return b


def is_game(a):
    c = (a.get("category") or "").lower()
    return any(w in c for w in GAME_WORDS)


def is_store_link(a):
    """True for listings that just point to the official Google Play page."""
    return "play.google.com" in (a.get("url") or "")


# ---------------------------------------------------------------- loading screen
def asset(name):
    return os.path.join(HERE, name)


def make_image(name, fill=False):
    """Image from the app folder, or None if the file is missing (never crashes)."""
    path = asset(name)
    if not os.path.exists(path):
        return None
    try:
        return Image(source=path, fit_mode="fill" if fill else "contain")
    except Exception:
        try:
            return Image(source=path, allow_stretch=True, keep_ratio=not fill)
        except Exception:
            return None


def gradient_texture(c1, c2, w=64):
    from kivy.graphics.texture import Texture
    tex = Texture.create(size=(w, 1), colorfmt="rgba")
    buf = bytearray()
    for i in range(w):
        t = i / (w - 1)
        buf.extend(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        buf.append(255)
    tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
    return tex


class SplashBar(Widget):
    """Rounded progress bar with a cyan-to-purple fill."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.progress = 0.0
        try:
            self.tex = gradient_texture((34, 211, 238), (192, 90, 245))
        except Exception:
            self.tex = None
        self.bind(pos=self.redraw, size=self.redraw)

    def redraw(self, *a):
        from kivy.graphics import Color, RoundedRectangle
        self.canvas.clear()
        r = self.height / 2
        with self.canvas:
            Color(1, 1, 1, 0.12)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[r])
            if self.progress > 0:
                w = max(self.height, self.width * self.progress)
                if self.tex is not None:
                    Color(1, 1, 1, 1)
                    RoundedRectangle(pos=self.pos, size=(w, self.height), radius=[r],
                                     texture=self.tex)
                else:
                    Color(0.13, 0.83, 0.93, 1)
                    RoundedRectangle(pos=self.pos, size=(w, self.height), radius=[r])


class SplashSpinner(Widget):
    """Ring of eight dots with a moving bright head."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.phase = 0
        self.bind(pos=self.redraw, size=self.redraw)

    def redraw(self, *a):
        from kivy.graphics import Color, Ellipse
        self.canvas.clear()
        n = 8
        rad = min(self.width, self.height) / 2 * 0.8
        dot = rad * 0.3
        with self.canvas:
            for i in range(n):
                ang = -2 * math.pi * i / n + math.pi / 2
                lead = (self.phase - i) % n
                t = i / (n - 1)
                Color(0.13 + 0.62 * t, 0.83 - 0.48 * t, 0.93 + 0.03 * t,
                      max(0.15, 1 - lead / n))
                Ellipse(pos=(self.center_x + rad * math.cos(ang) - dot / 2,
                             self.center_y + rad * math.sin(ang) - dot / 2),
                        size=(dot, dot))


# ---------------------------------------------------------------- app
class StoreApp(App):

    # ============================================================ startup
    def build(self):
        self.title = "My Store"
        self.device = device_id()
        P["app_version"] = APP_VERSION          # the background service compares against this
        save_prefs()
        self.data, self.items = [], {}
        self.kind, self.cat, self._ev = "", "", None
        self.root_box = BoxLayout(orientation="vertical")
        paint(self.root_box, PAGE, 0)
        try:
            self.show_splash(self.start)      # animated loading screen, then start()
        except Exception:
            self.start()                      # if the splash ever fails, just start the app
        return self.root_box

    def start(self, *a):
        try:
            acct = self.active()
            if acct and P["accepted"].get(acct["email"]) == TERMS_VERSION:
                self.show_main()
            elif acct:
                self.show_terms(acct["email"], self.show_main, back=lambda: self.show_auth())
            elif P.get("guest") and P["accepted"].get("guest") == TERMS_VERSION:
                self.show_main()
            else:
                self.show_auth()
        except Exception:
            self.root_box.clear_widgets()
            self.root_box.add_widget(Label(text=traceback.format_exc(), font_size=dp(11)))

    def show_splash(self, done):
        from kivy.graphics import Color, Rectangle
        root = FloatLayout()
        with root.canvas.before:
            Color(0.02, 0.03, 0.09, 1)
            rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda i, v: setattr(rect, "pos", v),
                  size=lambda i, v: setattr(rect, "size", v))

        bg = make_image("splash_bg.png", fill=True)
        if bg:
            root.add_widget(bg)

        W = Window.width
        logo = make_image("logo.png")
        if logo:
            logo.size_hint = (None, None)
            logo.size = (W * 0.667, W * 0.667)
            logo.pos_hint = {"center_x": 0.5, "center_y": 0.60}
            root.add_widget(logo)

        title = make_image("title.png")
        if title:
            title.size_hint = (None, None)
            title.size = (W * 0.76, W * 0.76 * 240 / 1100)
            title.pos_hint = {"center_x": 0.5, "center_y": 0.445}
            root.add_widget(title)
        else:
            lbl = Label(text="[b]My [color=7c9cff]Store[/color][/b]", markup=True,
                        font_size="38sp", size_hint=(1, None), height=dp(60),
                        pos_hint={"center_x": 0.5, "center_y": 0.445})
            root.add_widget(lbl)

        root.add_widget(Label(text="Shop  \u00b7  Download  \u00b7  Enjoy", font_size="15sp",
                              color=(0.75, 0.78, 0.88, 1), size_hint=(1, None), height=dp(30),
                              pos_hint={"center_x": 0.5, "center_y": 0.40}))

        bar = SplashBar(size_hint=(0.6, None), height=dp(8),
                        pos_hint={"center_x": 0.5, "center_y": 0.35})
        spin = SplashSpinner(size_hint=(None, None), size=(dp(36), dp(36)),
                             pos_hint={"center_x": 0.5, "center_y": 0.29})
        root.add_widget(bar)
        root.add_widget(spin)
        self.show(root)

        state = {"t": 0.0, "done": False}

        def tick(dt):
            if state["done"]:
                return False
            state["t"] += dt
            bar.progress = min(1.0, state["t"] / SPLASH_SECONDS)
            bar.redraw()
            spin.phase = int(state["t"] * 10) % 8
            spin.redraw()
            if state["t"] >= SPLASH_SECONDS:
                state["done"] = True
                done()
                return False
        Clock.schedule_interval(tick, 1 / 30.0)

    def show(self, widget):
        self.root_box.clear_widgets()
        self.root_box.add_widget(widget)

    def active(self):
        for a in P["accounts"]:
            if a["email"] == P["active"]:
                return a
        return None

    def token(self):
        a = self.active()
        return a["token"] if a else None

    def add_account(self, res):
        u = res["user"]
        email = u["email"].lower()
        accs = [a for a in P["accounts"] if a["email"] != email]
        accs.append({"email": email, "name": u["name"], "token": res["token"],
                     "provider": u.get("provider", "password")})
        P["accounts"] = accs
        P["active"] = email
        P["guest"] = False
        save_prefs()

    def notice(self, msg):
        """Small rounded toast near the bottom of the screen."""
        try:
            tag = BoxLayout(size_hint=(None, None), size=(min(Window.width * 0.88, dp(420)), dp(50)),
                            padding=[dp(16), 0])
            paint(tag, (0.14, 0.18, 0.38, 1), 25)
            tag.add_widget(text(esc(msg), size="14sp", color=TXT, halign="center"))
            tag.pos = ((Window.width - tag.width) / 2, dp(90))
            Window.add_widget(tag)
            Clock.schedule_once(lambda dt: Window.remove_widget(tag), 2.4)
        except Exception:
            self.say(msg)

    # ============================================================ sign in / sign up
    def show_auth(self, mode="signin", message="", prefill="", can_cancel=False):
        signup = mode == "signup"
        sv = ScrollView()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12),
                        padding=[dp(22), dp(34), dp(22), dp(24)])
        col.bind(minimum_height=col.setter("height"))

        logo = AnchorLayout(size_hint_y=None, height=dp(84))
        tile = BoxLayout(size_hint=(None, None), size=(dp(76), dp(76)))
        paint(tile, ACCENT, 22)
        tile.add_widget(text("[b]S[/b]", size="40sp", color=WHITE, halign="center"))
        logo.add_widget(tile)
        col.add_widget(logo)
        col.add_widget(text("[b]Welcome to My Store[/b]", size="24sp", height=dp(40),
                            halign="center"))
        col.add_widget(text("Sign in or create an account to browse, install and verify apps.",
                            size="13sp", color=GRAY, height=dp(40), halign="center"))

        tabs = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        for label, m in (("Sign in", "signin"), ("Create account", "signup")):
            on = (m == mode)
            b = pill(label, ACCENT if on else CHIP_BG, WHITE if on else DARK, h=44)
            b.bind(on_release=lambda i, mm=m: self.show_auth(mm, can_cancel=can_cancel))
            tabs.add_widget(b)
        col.add_widget(tabs)

        name_in = pw2_in = None
        if signup:
            box, name_in = field("Display name")
            col.add_widget(box)
        box, email_in = field("Email", default=prefill)
        col.add_widget(box)
        box, pw_in = field("Password (8+ characters)" if signup else "Password", password=True)
        col.add_widget(box)
        if signup:
            box, pw2_in = field("Confirm password", password=True)
            col.add_widget(box)

        err = text(esc(message), size="13sp", color=RED, height=dp(36))
        col.add_widget(err)

        go = pill("Create account" if signup else "Sign in", ACCENT, WHITE, h=52, size="16sp")

        def submit(*a):
            email = email_in.text.strip().lower()
            pw = pw_in.text
            if "@" not in email or "." not in email.split("@")[-1]:
                err.text = "Enter a valid email address"
                return
            if signup:
                nm = name_in.text.strip()
                if not nm:
                    err.text = "Enter a display name"
                    return
                if len(pw) < 8:
                    err.text = "Password must be at least 8 characters"
                    return
                if pw != pw2_in.text:
                    err.text = "Passwords do not match"
                    return
                self.show_terms(email, lambda: self.do_register(nm, email, pw),
                                back=lambda: self.show_auth("signup", prefill=email,
                                                            can_cancel=can_cancel))
            else:
                if not pw:
                    err.text = "Enter your password"
                    return
                err.color = GRAY
                err.text = "Signing in..."
                run_bg(lambda: call("/api/login", {"email": email, "password": pw}),
                       lambda res, e: self.after_auth(res, e, "signin", email))

        go.bind(on_release=submit)
        col.add_widget(go)

        google = pill("Continue with Google", WHITE, DARK, h=48, size="15sp")
        google.bind(on_release=lambda *a: self.google_login())
        col.add_widget(google)

        if not can_cancel:
            skip = pill("Skip for now", CHIP_BG, DARK, h=44, bold=False)
            skip.bind(on_release=lambda *a: self.skip_login())
            col.add_widget(skip)

        if can_cancel:
            cancel = pill("Cancel", CHIP_BG, DARK, h=44, bold=False)
            cancel.bind(on_release=lambda *a: self.show_main())
            col.add_widget(cancel)

        sv.add_widget(col)
        self.show(sv)

    def do_register(self, name, email, pw):
        self.notice("Sending your code...")
        run_bg(lambda: call("/api/register/start", {"name": name, "email": email, "password": pw}),
               lambda res, e: self.after_start(res, e, name, email))

    def after_start(self, res, err, name, email):
        if err:
            self.show_auth("signup", message=err, prefill=email)
            return
        self.show_verify(name, email)

    def show_verify(self, name, email, message="", info=""):
        sv = ScrollView()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12),
                        padding=[dp(22), dp(40), dp(22), dp(24)])
        col.bind(minimum_height=col.setter("height"))
        col.add_widget(text("[b]Check your email[/b]", size="24sp", height=dp(44), halign="center"))
        col.add_widget(auto_text("We sent a 6-digit code to [b]%s[/b]. Type it below to finish "
                                 "creating your account. It can take a minute, so check Spam too."
                                 % esc(email), size="13sp", color=GRAY))
        box, code_in = field("6-digit code")
        code_in.input_filter = "int"
        col.add_widget(box)
        err = text(esc(message or info), size="13sp", color=RED if message else GRAY, height=dp(36))
        col.add_widget(err)

        go = pill("Verify and create account", ACCENT, WHITE, h=52, size="16sp")

        def submit(*a):
            code = code_in.text.strip()
            if len(code) != 6 or not code.isdigit():
                err.color = RED
                err.text = "Enter the 6-digit code"
                return
            err.color = GRAY
            err.text = "Checking..."
            run_bg(lambda: call("/api/register/confirm", {"email": email, "code": code}),
                   lambda res, e: self.after_confirm(res, e, name, email))
        go.bind(on_release=submit)
        col.add_widget(go)

        again = pill("Send a new code", CHIP_BG, DARK, h=44, bold=False)

        def resend(*a):
            err.color = GRAY
            err.text = "Sending..."
            run_bg(lambda: call("/api/register/resend", {"email": email}),
                   lambda res, e: self.show_verify(name, email, message=e) if e
                   else self.show_verify(name, email, info="A new code was sent."))
        again.bind(on_release=resend)
        col.add_widget(again)

        back = pill("Back", CHIP_BG, DARK, h=44, bold=False)
        back.bind(on_release=lambda *a: self.show_auth("signup", prefill=email))
        col.add_widget(back)
        sv.add_widget(col)
        self.show(sv)

    def after_confirm(self, res, err, name, email):
        if err:
            self.show_verify(name, email, message=err)
            return
        self.after_auth(res, None, "signup", email)

    # ---- Google sign-in (the phone opens the browser; the server checks Google; a link brings us back)
    def google_login(self):
        self._google_state = uuid.uuid4().hex + uuid.uuid4().hex     # 64 characters, only this phone knows it
        self.open_url("%s/auth/google/start?state=%s" % (SERVER, self._google_state))

    def handle_link(self, url):
        try:
            u = urlparse(url or "")
            if u.scheme != "mystore" or u.netloc != "auth":
                return
            q = parse_qs(u.query)
            code, state = (q.get("code") or [""])[0], (q.get("state") or [""])[0]
        except Exception:
            return
        if not code or not getattr(self, "_google_state", None) or state != self._google_state:
            self.notice("That sign-in link is not for this phone")
            return
        self._google_state = None
        self.notice("Signing you in...")
        run_bg(lambda: call("/api/google/exchange", {"code": code}),
               lambda res, e: self.after_google(res, e))

    def after_google(self, res, err):
        if err:
            self.show_auth("signin", message=err)
            return
        self.after_auth(res, None, "google", res["user"]["email"])

    def on_new_intent(self, intent):
        url, target = "", ""
        try:
            data = intent.getData()
            url = data.toString() if data else ""
        except Exception:
            pass
        try:
            target = intent.getStringExtra("open") or ""
        except Exception:
            pass
        if url:
            Clock.schedule_once(lambda dt: self.handle_link(url), 0)
        if target == "inbox":
            Clock.schedule_once(lambda dt: self.open_inbox(), 0.3)

    def on_start(self):
        try:
            from android import activity
            activity.bind(on_new_intent=self.on_new_intent)
            from jnius import autoclass
            intent = autoclass("org.kivy.android.PythonActivity").mActivity.getIntent()
            data = intent.getData()
            if data:
                url = data.toString()
                Clock.schedule_once(lambda dt: self.handle_link(url), 1.5)
            if (intent.getStringExtra("open") or "") == "inbox":      # opened by tapping a notification
                Clock.schedule_once(lambda dt: self.open_inbox(), SPLASH_SECONDS + 1.5)
        except Exception:
            pass                      # not on a phone

    def on_pause(self):
        return True                   # stay alive while the browser or installer is on screen

    def on_resume(self):
        path = getattr(self, "_pending_install", None)
        if path and self.can_install():
            self._pending_install = None
            Clock.schedule_once(lambda dt: self.try_install(path), 0.5)
        return True

    def ask_permissions(self):
        """Ask once for notifications (and storage on old phones)."""
        if P.get("perm_asked"):
            return
        try:
            from android.permissions import request_permissions
            request_permissions(["android.permission.POST_NOTIFICATIONS",
                                 "android.permission.WRITE_EXTERNAL_STORAGE",
                                 "android.permission.READ_EXTERNAL_STORAGE"])
            P["perm_asked"] = True
            save_prefs()
        except Exception:
            pass                      # not on a phone

    def notify(self, title, message):
        try:
            from jnius import autoclass
            from store_notify import post_notification
            post_notification(autoclass("org.kivy.android.PythonActivity").mActivity, title, message, kind="test")
        except Exception:
            self.notice(message)

    def sync_service(self):
        """Run the update checker in the background only when there is something to watch."""
        try:
            from jnius import autoclass
            Activity = autoclass("org.kivy.android.PythonActivity").mActivity
            service = autoclass("org.mystore.mystore.ServiceUpdates")
            if P.get("notify_updates", True):
                service.start(Activity, "")
            else:
                service.stop(Activity)
        except Exception:
            pass                      # not on a phone, or the service is not in this build

    def open_url(self, url):
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            Activity = autoclass("org.kivy.android.PythonActivity")
            i = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            Activity.mActivity.startActivity(i)
        except Exception:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                self.say("Open this link in your browser: " + url)

    def is_guest(self):
        return self.active() is None

    def skip_login(self):
        if P["accepted"].get("guest") == TERMS_VERSION:
            self.enter_guest()
        else:
            self.show_terms("guest", self.enter_guest, back=lambda: self.show_auth())

    def enter_guest(self):
        P["guest"] = True
        save_prefs()
        self.show_main()

    def need_login(self, what):
        self.popup("Sign in required",
                   "You need an account to %s. Browsing is free for guests." % what,
                   yes=lambda: self.show_auth("signin", can_cancel=True), yes_label="Sign in")

    def after_auth(self, res, err, mode, email):
        if err:
            self.show_auth(mode, message=err, prefill=email)
            return
        self.add_account(res)
        if P["accepted"].get(email) == TERMS_VERSION:
            self.show_main()
        else:
            self.show_terms(email, self.show_main, back=lambda: self.show_auth(mode, prefill=email))

    # ============================================================ terms & policy (screen 2)
    def show_terms(self, email, on_accept, back):
        acc = {k: False for k, _, _ in POLICIES}
        root = BoxLayout(orientation="vertical", spacing=dp(8))

        head = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(96),
                         padding=[dp(18), dp(16), dp(18), dp(12)])
        paint(head, HEADER, [0, 0, 26, 26])
        head.add_widget(text("Step 2 of 2", size="12sp", color=(1, 1, 1, 0.8), height=dp(18)))
        head.add_widget(text("[b]Terms & policies[/b]", size="22sp", color=WHITE))
        root.add_widget(head)

        intro = BoxLayout(size_hint_y=None, height=dp(26), padding=[dp(18), 0])
        intro.add_widget(text("Please read and agree to each one to continue.",
                              size="13sp", color=GRAY))
        root.add_widget(intro)

        sv = vscroll()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10),
                        padding=[dp(14), dp(4), dp(14), dp(8)])
        col.bind(minimum_height=col.setter("height"))

        cont = pill("Accept & continue", ACCENT, WHITE, h=52, size="16sp")
        cont.opacity = 0.45
        msg = text("", size="12sp", color=RED, height=dp(20))

        for key, title, body in POLICIES:
            card = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8),
                             padding=dp(14))
            card.bind(minimum_height=card.setter("height"))
            paint(card, WHITE, 18)
            card.add_widget(text("[b]%s[/b]" % title, size="16sp", height=dp(24)))
            card.add_widget(auto_text(body, size="13sp", color=GRAY))
            agree = pill("I agree", CHIP_BG, DARK, h=36, size="13sp", bold=False)

            def toggle(inst, k=key):
                acc[k] = not acc[k]
                inst.text = "Agreed" if acc[k] else "I agree"
                inst.color = ACCENT if acc[k] else DARK
                inst.bold = acc[k]
                cont.opacity = 1 if all(acc.values()) else 0.45
                msg.text = ""
            agree.bind(on_release=toggle)
            card.add_widget(agree)
            col.add_widget(card)
        sv.add_widget(col)
        root.add_widget(sv)

        def accept(*a):
            if not all(acc.values()):
                msg.text = "Please agree to all three to continue."
                return
            P["accepted"][email] = TERMS_VERSION
            save_prefs()
            on_accept()
        cont.bind(on_release=accept)

        bottom = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(150),
                           padding=[dp(18), dp(4), dp(18), dp(14)], spacing=dp(6))
        bottom.add_widget(msg)
        bottom.add_widget(cont)
        bk = pill("Back", CHIP_BG, DARK, h=40, bold=False)
        bk.bind(on_release=lambda *a: back())
        bottom.add_widget(bk)
        root.add_widget(bottom)
        self.show(root)

    # ============================================================ main shell
    def show_main(self):
        self.store_view = self.build_store()
        self.content = BoxLayout()
        nav = BoxLayout(size_hint_y=None, height=dp(66), padding=[dp(6), dp(6)], spacing=dp(2))
        paint(nav, NAV_BG, [20, 20, 0, 0])
        self.nav_items = {}
        for key, label, icon in (("home", "Home", "nav_home.png"), ("games", "Games", "nav_games.png"),
                                 ("apps", "Apps", "nav_apps.png"),
                                 ("downloads", "Downloads", "nav_downloads.png"),
                                 ("profile", "Profile", "nav_profile.png")):
            item = TapBox(orientation="vertical", spacing=dp(2), padding=[0, dp(2), 0, 0])
            img = make_image(icon)
            if img is None:
                img = Widget()
            img.size_hint_y = 0.62
            lbl = Label(text=label, font_size="11sp", color=SUB, size_hint_y=0.38)
            item.add_widget(img)
            item.add_widget(lbl)
            item.bind(on_release=lambda *a, k=key: self.switch_tab(k))
            self.nav_items[key] = (img, lbl)
            nav.add_widget(item)
        col = BoxLayout(orientation="vertical")
        paint(col, NAVY, 0)
        col.add_widget(self.content)
        col.add_widget(nav)
        self.show(col)
        self.switch_tab("home")
        self.load()
        Clock.schedule_once(lambda dt: self.ask_permissions(), 1.5)
        Clock.schedule_once(lambda dt: self.sync_service(), 3)
        Clock.schedule_once(lambda dt: self.check_self_update(), 4)

    def switch_tab(self, key):
        key = {"store": "home", "settings": "profile"}.get(key, key)
        self.content.clear_widgets()
        if key == "profile":
            self.content.add_widget(self.build_settings())
        elif key == "downloads":
            self.content.add_widget(self.build_downloads())
        else:
            self.content.add_widget(self.store_view)
            self.set_mode(key if key in ("home", "games", "apps") else "home")
        self.tab = key
        self.update_nav(key)

    def update_nav(self, key):
        for k, (img, lbl) in self.nav_items.items():
            col = CYAN if k == key else SUB
            lbl.color = col
            lbl.bold = (k == key)
            try:
                img.color = col
            except Exception:
                pass

    # ============================================================ home / store tab
    def build_store(self):
        self.mode, self.kind, self.cat = "home", "", ""
        self.limit = 60                      # apps shown in a results list before "Show more"
        self.sort = P["sort"]
        view = BoxLayout(orientation="vertical", spacing=dp(6))
        paint(view, NAVY, 0)

        head = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(142),
                         padding=[dp(14), dp(12), dp(14), dp(2)], spacing=dp(10))
        top = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(10))
        logo = make_image(HOME_LOGO)
        logo_tap = TapBox(size_hint=(1, 1))
        if logo:
            logo_tap.add_widget(logo)
        else:
            logo_tap.add_widget(avatar("M", 56, bg=ACCENT, fg=WHITE))
        logo_tap.bind(on_release=lambda *a: self.open_inbox())
        logo_box = FloatLayout(size_hint=(None, None), size=(dp(58), dp(58)))
        logo_box.add_widget(logo_tap)
        self.badge = Label(text="", font_size="10sp", bold=True, color=WHITE, size_hint=(None, None),
                           size=(dp(20), dp(20)), pos_hint={"right": 1, "top": 1}, opacity=0)
        paint(self.badge, RED, 10)
        logo_box.add_widget(self.badge)
        top.add_widget(logo_box)
        self.update_badge()
        tcol = BoxLayout(orientation="vertical", spacing=dp(2))
        title = make_image("title_tight.png")
        if title:
            title.size_hint = (None, None)
            title.size = (dp(158), dp(32))
            tcol.add_widget(title)
        else:
            tcol.add_widget(text("[b]My [color=22d3ee]Store[/color][/b]", size="26sp", color=TXT,
                                 height=dp(34)))
        tcol.add_widget(text("Discover  \u00b7  Download  \u00b7  Enjoy", size="12sp", color=SUB,
                             height=dp(18)))
        top.add_widget(tcol)

        sbtn = TapBox(size_hint=(None, None), size=(dp(46), dp(46)), padding=dp(12))
        paint(sbtn, CARD_D, 23)
        ic = make_image("ic_search.png")
        if ic:
            ic.color = CYAN
            sbtn.add_widget(ic)
        sbtn.bind(on_release=lambda *a: setattr(self.search, "focus", True))
        holder = AnchorLayout(size_hint=(None, 1), width=dp(46))
        holder.add_widget(sbtn)
        top.add_widget(holder)
        head.add_widget(top)

        bar = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(14), 0, dp(4), 0], spacing=dp(6))
        paint(bar, CARD_D, 24)
        mag = make_image("ic_search.png")
        if mag:
            mag.color = SUB
            mag.size_hint = (None, None)
            mag.size = (dp(20), dp(20))
            mh = AnchorLayout(size_hint=(None, 1), width=dp(22))
            mh.add_widget(mag)
            bar.add_widget(mh)
        self.search = TextInput(hint_text="Search apps, games, and more...", multiline=False,
                                background_normal="", background_active="",
                                background_color=(0, 0, 0, 0), foreground_color=TXT,
                                hint_text_color=SUB, cursor_color=CYAN,
                                padding=[dp(4), dp(14), dp(4), dp(10)])
        self.search.bind(text=self.on_search_text)
        clear = Button(text="X", size_hint_x=None, width=dp(44), background_normal="",
                       background_down="", background_color=(0, 0, 0, 0), color=SUB, bold=True)
        clear.bind(on_release=lambda *a: setattr(self.search, "text", ""))
        bar.add_widget(self.search)
        bar.add_widget(clear)
        head.add_widget(bar)
        view.add_widget(head)

        self.chip_row = self.make_chip_row()
        self.kind_row = self.make_chip_row()
        view.add_widget(self.chip_row[0])
        view.add_widget(self.kind_row[0])
        self.refresh_chips()
        self.refresh_kinds()

        self.srow = BoxLayout(size_hint_y=None, height=dp(34), padding=[dp(14), 0])
        self.status = text("", size="12sp", color=SUB)
        self.sort_btn = pill("Sort: Popular" if self.sort == "popular" else "Sort: Newest",
                             LINE_D, TXT, h=30, size="12sp", bold=False)
        self.sort_btn.size_hint_x = None
        self.sort_btn.width = dp(120)
        self.sort_btn.bind(on_release=lambda *a: self.toggle_sort())
        self.srow.add_widget(self.status)
        self.srow.add_widget(self.sort_btn)
        view.add_widget(self.srow)

        scroll = vscroll()
        self.box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(14),
                             padding=[dp(12), dp(4), dp(12), dp(16)])
        self.box.bind(minimum_height=self.box.setter("height"))
        scroll.add_widget(self.box)
        view.add_widget(scroll)
        self.set_results_chrome(False)
        return view

    def make_chip_row(self):
        sv = ScrollView(size_hint_y=None, height=dp(42), do_scroll_y=False, bar_width=0)
        inner = BoxLayout(size_hint_x=None, spacing=dp(8), padding=[dp(12), dp(3)])
        inner.bind(minimum_width=inner.setter("width"))
        sv.add_widget(inner)
        return sv, inner

    def chip(self, label, active, action):
        b = Button(text=esc(label), size_hint=(None, 1), width=dp(34) + dp(8) * len(label),
                   background_normal="", background_down="", background_color=(0, 0, 0, 0),
                   color=CYAN if active else TXT, font_size="13sp", bold=active)
        paint(b, CHIP_ON if active else CARD_D, 18)
        b.bind(on_release=lambda *a: action())
        return b

    def chip_icon(self, label, icon, active, action):
        w = TapBox(size_hint=(None, 1), width=dp(50) + dp(8.4) * len(label),
                   padding=[dp(12), 0, dp(14), 0], spacing=dp(6))
        paint(w, CHIP_ON if active else CARD_D, 18)
        img = make_image(icon)
        if img is not None:
            img.size_hint = (None, None)
            img.size = (dp(18), dp(18))
            img.color = CYAN if active else TXT
            holder = AnchorLayout(size_hint=(None, 1), width=dp(18))
            holder.add_widget(img)
            w.add_widget(holder)
        w.add_widget(Label(text=label, font_size="13sp", bold=active, color=CYAN if active else TXT))
        w.bind(on_release=lambda *a: action())
        return w

    def refresh_chips(self):
        inner = self.chip_row[1]
        inner.clear_widgets()
        active = "cats" if self.cat else self.mode
        for label, key, icon in (("Home", "home", "nav_home.png"), ("Games", "games", "nav_games.png"),
                                 ("Apps", "apps", "nav_apps.png"), ("Top Charts", "top", "ic_chart.png"),
                                 ("Categories", "cats", "ic_grid.png")):
            inner.add_widget(self.chip_icon(label, icon, active == key, lambda k=key: self.chip_action(k)))

    def chip_action(self, key):
        if key == "cats":
            self.category_popup()
        else:
            self.set_mode(key)

    def refresh_kinds(self):
        inner = self.kind_row[1]
        inner.clear_widgets()
        for label, kind in (("All", ""), ("Originals", "original"),
                            ("Mods", "mod"), ("Other stores", "external")):
            inner.add_widget(self.chip(label, self.kind == kind, lambda k=kind: self.set_kind(k)))

    def set_mode(self, mode, reload=False):
        self.mode = mode
        self.cat = ""
        self.limit = 60
        self.refresh_chips()
        if self.tab_is_store():
            self.update_nav(mode if mode in ("home", "games") else "apps")
        if reload:
            self.load()
        else:
            self.render()

    def tab_is_store(self):
        return getattr(self, "tab", "home") in ("home", "games", "apps", "top")

    def category_popup(self):
        cats = sorted({a["category"] for a in self.data if a.get("category")})
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        sv = ScrollView()
        lst = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        lst.bind(minimum_height=lst.setter("height"))
        pop = Dialog(title="Categories", content=box, size_hint=(0.9, 0.7))

        def pick(c):
            pop.dismiss()
            self.limit = 60
            self.cat = c
            self.refresh_chips()
            self.render()
        for c in [""] + cats:
            b = pill(c or "All categories", CHIP_ON if c == self.cat else LINE_D, TXT, h=42, size="14sp",
                     bold=(c == self.cat))
            b.bind(on_release=lambda *a, cc=c: pick(cc))
            lst.add_widget(b)
        sv.add_widget(lst)
        box.add_widget(sv)
        pop.open()

    def on_search_text(self, inst, value):
        self.limit = 60
        if self._ev:
            self._ev.cancel()
        self._ev = Clock.schedule_once(lambda dt: self.load(), 0.5)

    def set_kind(self, kind):
        self.limit = 60
        self.kind = kind
        self.refresh_kinds()
        self.load()

    def toggle_sort(self):
        self.limit = 60
        self.sort = "new" if self.sort == "popular" else "popular"
        self.sort_btn.text = "Sort: Popular" if self.sort == "popular" else "Sort: Newest"
        self.render()

    def set_results_chrome(self, on):
        for w, h in ((self.kind_row[0], 42), (self.srow, 34)):
            w.height = dp(h) if on else 0
            w.opacity = 1 if on else 0
            w.disabled = not on

    def say(self, msg):
        try:
            self.status.text = esc(msg)
        except Exception:
            pass

    def load(self):
        self.say("Loading...")
        path = "/api/apps?q=%s&kind=%s" % (quote(self.search.text.strip()), self.kind)
        tok = self.token()
        run_bg(lambda: call(path, token=tok), self.loaded)

    def loaded(self, data, err):
        if err == SESSION_EXPIRED:
            self.drop_active("Session expired. Please sign in again.")
            return
        if err:
            self.say("Can't reach server: " + err)
            self.set_results_chrome(True)
            return
        self.data = data
        self.render()
        pend = getattr(self, "_pending_details", None)
        if pend is not None:
            self._pending_details = None
            if pend in self.items:
                self.details(pend)
            else:
                self.notice("That app is no longer in the store")

    def visible_rows(self):
        return [a for a in self.data
                if (P["show_mods"] or a["kind"] != "mod")
                and (P["show_external"] or a["kind"] != "external")]

    def render(self):
        self.items = {a["id"]: a for a in self.data}
        self.box.clear_widgets()
        rows = self.visible_rows()
        results = bool(self.search.text.strip()) or self.mode != "home" or bool(self.cat)
        self.set_results_chrome(results)
        if not results:
            self.render_home(rows)
            return
        if self.mode == "games":
            rows = [a for a in rows if is_game(a)]
        elif self.mode == "apps":
            rows = [a for a in rows if not is_game(a)]
        if self.cat:
            rows = [a for a in rows if a.get("category") == self.cat]
        if self.mode == "top" or self.sort == "popular":
            rows.sort(key=lambda a: a.get("downloads", 0), reverse=True)
        else:
            rows.sort(key=lambda a: a.get("id", 0), reverse=True)
        if not rows:
            self.box.add_widget(text("No apps found", size="16sp", color=SUB,
                                     height=dp(120), halign="center"))
        for a in rows[:self.limit]:
            self.box.add_widget(self.card(a))
        if len(rows) > self.limit:
            more = gpill("Show more  (%d left)" % (len(rows) - self.limit), BLUE_A, BLUE_B, h=46, size="14sp")
            more.bind(on_release=lambda *a: self.show_more())
            self.box.add_widget(more)
        self.say("%d apps" % len(rows))

    def show_more(self):
        self.limit += 60
        self.render()

    def render_home(self, rows):
        self.box.add_widget(self.banner())
        if not rows:
            self.box.add_widget(text("No apps yet. Pull the store together from the admin page.",
                                     size="14sp", color=SUB, height=dp(90), halign="center"))
            return
        by_dl = lambda items: sorted(items, key=lambda a: a.get("downloads", 0), reverse=True)[:20]
        sections = (
            ("Popular Apps", by_dl([a for a in rows if not is_game(a)]), ORANGE, "apps"),
            ("Top Games", by_dl([a for a in rows if is_game(a)]), VIOLET, "games"),
            ("Modded Versions", [a for a in rows if a["kind"] == "mod"][:20], RED, "mods"),
            ("New Arrivals", sorted(rows, key=lambda a: a.get("id", 0), reverse=True)[:20], CYAN, "new"),
        )
        for title, items, accent, which in sections:
            if items:
                self.box.add_widget(self.section(title, items, accent, which))

    def banner(self):
        ban = FloatLayout(size_hint_y=None, height=dp(176))
        paint(ban, BANNER_BG, 22)
        bg = make_image("banner.png", fill=True)
        if bg:
            ban.add_widget(bg)
        col = BoxLayout(orientation="vertical", size_hint=(0.58, 1), pos_hint={"x": 0, "y": 0},
                        padding=[dp(16), dp(14), dp(4), dp(14)], spacing=dp(4))
        tag_row = AnchorLayout(anchor_x="left", size_hint_y=None, height=dp(22))
        tag = Label(text="[b]FEATURED[/b]", markup=True, font_size="10sp", color=TXT,
                    size_hint=(None, None), size=(dp(82), dp(20)))
        paint(tag, TAG_BG, 10)
        tag_row.add_widget(tag)
        col.add_widget(tag_row)
        col.add_widget(text("[b]Best Apps\nFor You[/b]", size="22sp", color=TXT, height=dp(62)))
        col.add_widget(auto_text("Top rated apps, games and tools to make your life easier.",
                                 size="11sp", color=SUB))
        col.add_widget(Widget())
        go = gpill("Explore Now  >", CYAN_A, CYAN_B, h=36, size="13sp")
        go.size_hint_x = None
        go.width = dp(132)
        go.bind(on_release=lambda *a: self.set_mode("apps"))
        col.add_widget(go)
        ban.add_widget(col)
        return ban

    def section(self, title, items, accent, which):
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        box.bind(minimum_height=box.setter("height"))
        head = BoxLayout(size_hint_y=None, height=dp(30), padding=[dp(4), 0], spacing=dp(8))
        ic = make_image({"apps": "nav_apps.png", "games": "nav_games.png", "mods": "nav_downloads.png",
                         "new": "nav_home.png"}.get(which, "nav_apps.png"))
        if ic is not None:
            ic.size_hint = (None, None)
            ic.size = (dp(24), dp(24))
            ic.color = accent
            bh = AnchorLayout(size_hint=(None, 1), width=dp(28))
            bh.add_widget(ic)
        else:
            bar = Widget(size_hint=(None, None), size=(dp(5), dp(20)))
            paint(bar, accent, 3)
            bh = AnchorLayout(size_hint=(None, 1), width=dp(6))
            bh.add_widget(bar)
        head.add_widget(bh)
        head.add_widget(text("[b]%s[/b]" % esc(title), size="17sp", color=TXT))
        more = Button(text="See All  >", size_hint_x=None, width=dp(92), background_normal="",
                      background_down="", background_color=(0, 0, 0, 0), color=CYAN, font_size="13sp")
        more.bind(on_release=lambda *a: self.see_all(which))
        head.add_widget(more)
        box.add_widget(head)
        scroll = ScrollView(size_hint_y=None, height=dp(188), do_scroll_y=False, bar_width=0,
                       scroll_distance=dp(8), scroll_timeout=100)
        inner = BoxLayout(size_hint_x=None, spacing=dp(10), padding=[dp(2), 0, dp(2), 0])
        inner.bind(minimum_width=inner.setter("width"))
        for a in items:
            inner.add_widget(self.tile(a))
        scroll.add_widget(inner)
        box.add_widget(scroll)
        return box

    def see_all(self, which):
        if which == "mods":
            self.kind = "mod"
            self.refresh_kinds()
            self.set_mode("apps", reload=True)
        elif which == "new":
            self.sort = "new"
            self.sort_btn.text = "Sort: Newest"
            self.set_mode("apps")
        else:
            self.set_mode(which)

    def icon_url(self, a):
        u = (a.get("icon") or "").strip()
        if u.startswith("/"):
            u = SERVER + u
        return u if u.lower().startswith("https://") else ""

    def app_icon(self, a, size):
        """Brand-coloured tile first; the real picture replaces it when it has loaded."""
        bg, fg = brand(a["name"])
        holder = AnchorLayout(size_hint=(None, None), size=(dp(size), dp(size)))
        holder.add_widget(avatar(a["name"], size, bg=bg, fg=fg))
        url = self.icon_url(a)
        if url:
            path = cached_icon(url)
            if path:
                self.show_icon(holder, path, size)
            else:
                run_bg(lambda: fetch_icon(url),
                       lambda p, e, h=holder: self.show_icon(h, p, size) if p else None)
        return holder

    def show_icon(self, holder, path, size):
        try:
            icon = RoundedIcon(path, corner=size * 0.22, size_hint=(None, None), size=(dp(size), dp(size)))
            holder.clear_widgets()
            holder.add_widget(icon)
        except Exception:
            pass                      # keep the coloured tile

    def tile(self, a):
        """One app in a sideways row."""
        name = a["name"]
        color = ICON_COLORS[sum(ord(c) for c in name) % len(ICON_COLORS)]
        store = is_store_link(a)
        if store:
            meta = "Google Play"
        elif a["kind"] == "mod":
            meta = "[color=ff6655]MOD[/color]  -  %s dl" % a["downloads"]
        else:
            meta = "%s downloads" % a["downloads"]
        w = BoxLayout(orientation="vertical", size_hint=(None, None), size=(dp(122), dp(184)),
                      padding=dp(8), spacing=dp(6))
        paint(w, CARD_D, 18)
        top = TapBox(orientation="vertical", spacing=dp(2))
        art = AnchorLayout(size_hint_y=None, height=dp(66))
        art.add_widget(self.app_icon(a, 62))
        top.add_widget(art)
        top.add_widget(text("[b]%s[/b]" % esc(name), size="13sp", color=TXT, height=dp(20), shorten=True))
        top.add_widget(text(esc(a["category"]), size="11sp", color=SUB, height=dp(16), shorten=True))
        top.add_widget(text(meta, size="11sp", color=SUB, height=dp(16), shorten=True))
        top.bind(on_release=lambda *x, i=a["id"]: self.details(i))
        w.add_widget(top)
        btn = gpill("Open" if store else "Install", BLUE_A, BLUE_B, h=30, size="12sp")
        btn.bind(on_release=lambda *x, i=a["id"]: self.get_app(i))
        w.add_widget(btn)
        return w

    def card(self, a):
        """One app in a vertical results list."""
        name = a["name"]
        color = ICON_COLORS[sum(ord(c) for c in name) % len(ICON_COLORS)]
        store = is_store_link(a)
        if store:
            badge = "[color=4285f4]Opens in Google Play[/color]"
        else:
            if a.get("verified"):
                badge = "[color=0f9d58]Verified[/color]"
            else:
                badge = "[color=f59e0b]Unverified %d/%d[/color]" % (a["verify_votes"], a["threshold"])
            if a["kind"] == "mod":
                badge += "   [color=e53935][b]MOD[/b][/color]"
            elif a["kind"] == "external":
                badge += "   [color=4285f4]via %s[/color]" % esc(a["source"])

        card = BoxLayout(size_hint_y=None, height=dp(108), padding=dp(12), spacing=dp(12))
        paint(card, CARD_D, 18)
        card.add_widget(self.app_icon(a, 60))

        info = TapBox(orientation="vertical", spacing=dp(2))
        info.add_widget(text("[b]%s[/b]" % esc(name), size="16sp", color=TXT, height=dp(24), shorten=True))
        info.add_widget(text("%s  -  %s" % (esc(a["developer"]), esc(a["category"])),
                             size="12sp", color=SUB, height=dp(18), shorten=True))
        meta = "Google Play" if store else "%s downloads  -  v%s" % (a["downloads"], esc(a["version"]))
        info.add_widget(text(meta, size="12sp", color=SUB, height=dp(18), shorten=True))
        info.add_widget(text(badge, size="12sp", color=TXT))
        info.bind(on_release=lambda *x, i=a["id"]: self.details(i))
        card.add_widget(info)

        side = AnchorLayout(size_hint_x=None, width=dp(88))
        inst = gpill("Open" if store else "Install", BLUE_A, BLUE_B, h=36, size="13sp")
        inst.bind(on_release=lambda *x, i=a["id"]: self.get_app(i))
        side.add_widget(inst)
        card.add_widget(side)
        return card

    # ============================================================ notifications inbox + My Store update
    def unread_count(self):
        seen = P.get("inbox_seen", 0)
        return len([i for i in read_inbox() if i.get("t", 0) > seen])

    def update_badge(self):
        try:
            n = self.unread_count()
            self.badge.text = str(n) if n < 10 else "9+"
            self.badge.opacity = 1 if n else 0
        except Exception:
            pass

    def open_inbox(self):
        items = read_inbox()
        P["inbox_seen"] = time.time()
        save_prefs()
        root = BoxLayout(orientation="vertical", spacing=dp(6))
        paint(root, NAVY, 0)
        head = BoxLayout(size_hint_y=None, height=dp(66), padding=[dp(14), dp(12), dp(14), dp(6)], spacing=dp(10))
        back = pill("<  Back", LINE_D, TXT, h=42, size="14sp", bold=False)
        back.size_hint_x = None
        back.width = dp(92)
        back.bind(on_release=lambda *a: self.show_main())
        bh = AnchorLayout(size_hint=(None, 1), width=dp(92))
        bh.add_widget(back)
        head.add_widget(bh)
        head.add_widget(text("[b]Notifications[/b]", size="20sp", color=TXT))
        if items:
            clr = pill("Clear", LINE_D, TXT, h=38, size="13sp", bold=False)
            clr.size_hint_x = None
            clr.width = dp(72)
            clr.bind(on_release=lambda *a: (clear_inbox(), self.open_inbox()))
            ch = AnchorLayout(size_hint=(None, 1), width=dp(72))
            ch.add_widget(clr)
            head.add_widget(ch)
        root.add_widget(head)
        sv = vscroll()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10),
                        padding=[dp(14), dp(4), dp(14), dp(28)])
        col.bind(minimum_height=col.setter("height"))
        if not items:
            col.add_widget(text("No notifications yet.\nNew apps and updates show up here.",
                                size="14sp", color=SUB, height=dp(120), halign="center"))
        for it in items:
            col.add_widget(self.inbox_row(it))
        sv.add_widget(col)
        root.add_widget(sv)
        self.show(root)

    def inbox_row(self, it):
        kind = it.get("kind", "")
        color = {"new": CYAN, "update": ORANGE, "self": VIOLET}.get(kind, SUB)
        card = TapBox(orientation="vertical", size_hint_y=None, padding=dp(14), spacing=dp(4))
        card.bind(minimum_height=card.setter("height"))
        paint(card, CARD_D, 18)
        top = BoxLayout(size_hint_y=None, height=dp(20))
        top.add_widget(text("[b]%s[/b]" % esc(KINDS.get(kind, kind or "Notice").upper()), size="11sp", color=color))
        top.add_widget(text(ago(it.get("t", 0)), size="11sp", color=SUB, halign="right"))
        card.add_widget(top)
        card.add_widget(text("[b]%s[/b]" % esc(it.get("title", "")), size="15sp", color=TXT, height=dp(24)))
        card.add_widget(auto_text(esc(it.get("message", "")), size="13sp", color=SUB))
        card.bind(on_release=lambda *a, x=it: self.inbox_tap(x))
        return card

    def inbox_tap(self, it):
        if it.get("kind") == "self":
            self.show_main()
            self.switch_tab("profile")
        elif it.get("app_id") is not None:
            self._pending_details = it["app_id"]      # open the app once the list has loaded
            self.show_main()

    def check_self_update(self):
        run_bg(lambda: call("/api/self"), self.got_self)

    def got_self(self, info, err):
        if err or not info or not info.get("version") or not info.get("url"):
            return
        if is_newer(info["version"], APP_VERSION):
            self.self_info = info
            if P.get("self_toast") != info["version"]:
                P["self_toast"] = info["version"]
                save_prefs()
                self.notice("My Store %s is ready - see Profile" % info["version"])
        else:
            self.self_info = None

    def update_self(self):
        info = getattr(self, "self_info", None)
        if not info:
            return
        path = os.path.join(save_dir(), "MyStore_%s.apk" % "".join(c if c.isalnum() or c == "." else "_" for c in info["version"]))
        self.notice("Downloading My Store %s ..." % info["version"])
        run_bg(lambda: fetch_file(info["url"], path, None),
               lambda digest, err: self.self_downloaded(info, path, digest, err))

    def self_downloaded(self, info, path, digest, err):
        if err:
            self.notice("Download failed: " + err)
            return
        if info.get("sha256") and digest.lower() != info["sha256"].lower():
            os.remove(path)
            self.popup("Blocked", "The update does not match its checksum and was deleted.")
            return
        P["downloads"] = (P["downloads"] + [path])[-50:]
        save_prefs()
        self.try_install(path)

    # ============================================================ downloads tab
    def build_downloads(self):
        sv = vscroll()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10),
                        padding=[dp(14), dp(18), dp(14), dp(24)])
        col.bind(minimum_height=col.setter("height"))
        col.add_widget(text("[b]Downloads[/b]", size="24sp", color=TXT, height=dp(40)))
        files = [p for p in P["downloads"] if os.path.exists(p)]
        if not files:
            col.add_widget(text("Nothing downloaded yet.\nApps you install from My Store show up here.",
                                size="14sp", color=SUB, height=dp(110), halign="center"))
        for p in reversed(files):
            row = BoxLayout(size_hint_y=None, height=dp(66), padding=dp(10), spacing=dp(8))
            paint(row, CARD_D, 16)
            row.add_widget(text(esc(os.path.basename(p)), size="13sp", color=TXT, shorten=True))
            ih = AnchorLayout(size_hint_x=None, width=dp(84))
            inst = gpill("Install", BLUE_A, BLUE_B, h=34, size="12sp")
            inst.bind(on_release=lambda *a, pp=p: self.try_install(pp))
            ih.add_widget(inst)
            row.add_widget(ih)
            dh = AnchorLayout(size_hint_x=None, width=dp(74))
            rm = pill("Delete", LINE_D, TXT, h=34, size="12sp", bold=False)
            rm.bind(on_release=lambda *a, pp=p: self.delete_download(pp))
            dh.add_widget(rm)
            row.add_widget(dh)
            col.add_widget(row)
        sv.add_widget(col)
        return sv

    def delete_download(self, path):
        try:
            os.remove(path)
        except Exception:
            pass
        P["downloads"] = [p for p in P["downloads"] if p != path]
        save_prefs()
        self.switch_tab("downloads")

    # ============================================================ popups
    def popup(self, title, msg, yes=None, yes_label="Continue", extra=None):
        box = BoxLayout(orientation="vertical", spacing=dp(10))
        sv = vscroll()
        sv.add_widget(auto_text(msg, size="14sp", color=TXT))
        box.add_widget(sv)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        pop = Dialog(title=title, content=box, size_hint=(0.92, 0.6))
        close = pill("Cancel" if yes else "Close", LINE_D, TXT, h=44, size="14sp", bold=False)
        close.bind(on_release=lambda *a: pop.dismiss())
        row.add_widget(close)
        if extra:
            b = pill(extra[0], LINE_D, CYAN, h=44, size="14sp", bold=False)
            b.bind(on_release=lambda *a: (pop.dismiss(), extra[1]()))
            row.add_widget(b)
        if yes:
            ok = gpill(yes_label, BLUE_A, BLUE_B, h=44, size="14sp")
            ok.bind(on_release=lambda *a: (pop.dismiss(), yes()))
            row.add_widget(ok)
        box.add_widget(row)
        pop.open()

    def form_popup(self, title, intro, fields, submit_label, on_submit):
        """fields: [(hint, is_password, default)]. on_submit(values, msg_label, popup)."""
        box = BoxLayout(orientation="vertical", spacing=dp(8))
        if intro:
            box.add_widget(auto_text(intro, size="13sp", color=SUB))
        inputs = []
        for hint, pw, default in fields:
            b, ti = field(hint, pw, default)
            box.add_widget(b)
            inputs.append(ti)
        msg = text("", size="12sp", color=(1, 0.55, 0.55, 1), height=dp(32))
        box.add_widget(msg)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        pop = Dialog(title=title, content=box, size_hint=(0.94, None),
                     height=dp(230 + 62 * len(fields) + (50 if intro else 0)))
        cancel = pill("Cancel", LINE_D, TXT, h=44, size="14sp", bold=False)
        cancel.bind(on_release=lambda *a: pop.dismiss())
        go = gpill(submit_label, BLUE_A, BLUE_B, h=44, size="14sp")
        go.bind(on_release=lambda *a: on_submit([i.text for i in inputs], msg, pop))
        row.add_widget(cancel)
        row.add_widget(go)
        box.add_widget(row)
        pop.open()

    def text_popup(self, title, body):
        self.popup(title, esc(body))

    def policy_page(self, title, body):
        root = BoxLayout(orientation="vertical", spacing=dp(6))
        paint(root, NAVY, 0)
        head = BoxLayout(size_hint_y=None, height=dp(66), padding=[dp(14), dp(12), dp(14), dp(6)], spacing=dp(12))
        back = pill("<  Back", LINE_D, TXT, h=42, size="14sp", bold=False)
        back.size_hint_x = None
        back.width = dp(96)
        back.bind(on_release=lambda *a: self.back_to_settings())
        bh = AnchorLayout(size_hint=(None, 1), width=dp(96))
        bh.add_widget(back)
        head.add_widget(bh)
        head.add_widget(text("[b]%s[/b]" % esc(title), size="20sp", color=TXT))
        root.add_widget(head)

        sv = vscroll()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12),
                        padding=[dp(14), dp(4), dp(14), dp(28)])
        col.bind(minimum_height=col.setter("height"))
        card = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(18), spacing=dp(12))
        card.bind(minimum_height=card.setter("height"))
        paint(card, CARD_D, 22)
        line = Widget(size_hint_y=None, height=dp(4))
        paint_grad(line, CYAN_A, VIOLET, 2)
        card.add_widget(line)
        for sentence in [s.strip() for s in body.replace("\n", " ").split(". ") if s.strip()]:
            if not sentence.endswith("."):
                sentence += "."
            lbl = auto_text("[color=22d3ee][b]-[/b][/color]  " + esc(sentence), size="15sp", color=TXT)
            lbl.line_height = 1.25
            card.add_widget(lbl)
        card.add_widget(text("Terms version %s" % TERMS_VERSION, size="12sp", color=SUB, height=dp(22)))
        col.add_widget(card)
        sv.add_widget(col)
        root.add_widget(sv)
        self.show(root)

    # ============================================================ details / install
    def details(self, app_id):
        a = self.items[app_id]
        if is_store_link(a):
            self.popup("App details", "[b]%s[/b]\nby %s\n%s\n\nThis opens the official Google Play page."
                       % (esc(a["name"]), esc(a["developer"]), esc(a["category"])),
                       extra=("Report", lambda: self.report(app_id)))
            return
        notes = ""
        if a["kind"] == "mod":
            notes = "\n[color=ff6655]Unofficial mod of %s. Use at your own risk.[/color]" % esc(a["mod_of"])
        msg = ("[b]%s[/b]  v%s\nby %s\n%s  -  %s downloads\n\n%s\n\n"
               "Verified by %d of %d people\nSHA-256: %s%s") % (
            esc(a["name"]), esc(a["version"]), esc(a["developer"]), esc(a["category"]),
            a["downloads"], esc(a["description"] or "No description."),
            a["verify_votes"], a["threshold"], (a.get("sha256") or "n/a")[:20] + "...", notes)
        self.popup("App details", msg, extra=("Report", lambda: self.report(app_id)))

    def get_app(self, app_id):
        if self.is_guest():
            self.need_login("install apps")
            return
        a = self.items[app_id]
        if is_store_link(a):
            self.open_store_page(a)
            return
        warn = ""
        if not a.get("verified") and P["warn_unverified"]:
            warn += "This app is NOT verified yet.\n"
        if a["kind"] == "mod":
            warn += "Mods are unofficial and can contain malware.\n"
        if warn:
            self.popup("Install anyway?", esc(warn) + "Only continue if you trust the source.",
                       yes=lambda: self.download(a), yes_label="Install")
        else:
            self.download(a)

    def download(self, a):
        safe = "".join(c if c.isalnum() else "_" for c in a["name"])
        path = os.path.join(save_dir(), "%s_%s.apk" % (safe, a["id"]))
        own = a["source"] == "own"
        url = ("%s/api/download/%s" % (SERVER, a["id"])) if own else a["url"]
        tok = self.token() if own else None      # never send your token to other sites
        self.say("Downloading %s ..." % a["name"])
        run_bg(lambda: fetch_file(url, path, tok),
               lambda digest, err: self.downloaded(a, path, digest, err))

    def open_store_page(self, a):
        tok = self.token()
        run_bg(lambda: call("/api/track/%s" % a["id"], {"event": "download"}, tok),
               lambda r, e: None)
        self.open_url(a["url"])

    def downloaded(self, a, path, digest, err):
        if err:
            self.say("Download failed: " + err)
            return
        if a.get("sha256") and digest.lower() != a["sha256"].lower():
            os.remove(path)
            self.say("Checksum mismatch - file deleted")
            self.popup("Blocked", "The file does not match the published checksum and was deleted.")
            return
        if a["source"] != "own":          # downloads from other sites are counted by telling the server
            tok = self.token()
            run_bg(lambda: call("/api/track/%s" % a["id"], {"event": "download"}, tok),
                   lambda r, e: None)
        P["downloads"] = (P["downloads"] + [path])[-50:]
        P.setdefault("tracked", {})[str(a["id"])] = {"name": a["name"], "version": a["version"]}
        save_prefs()
        self.sync_service()
        self.say("Saved: " + path)
        self.try_install(path)
        if P["ask_verify"]:
            self.popup("Did it install and work?",
                       "If yes, you can help verify this app (one vote per account).",
                       yes=lambda: self.vote(a["id"]), yes_label="Yes, verify")

    def can_install(self):
        """True when Android lets My Store install apps (or the phone is old enough not to ask)."""
        try:
            from jnius import autoclass
            Activity = autoclass("org.kivy.android.PythonActivity").mActivity
            if autoclass("android.os.Build$VERSION").SDK_INT < 26:
                return True
            return bool(Activity.getPackageManager().canRequestPackageInstalls())
        except Exception:
            return True

    def open_install_settings(self):
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            Settings = autoclass("android.provider.Settings")
            Activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                          Uri.parse("package:" + Activity.getPackageName())))
        except Exception:
            self.say("Open Android Settings > Apps > My Store and allow installing apps")

    def try_install(self, path):
        try:
            from jnius import autoclass
        except Exception:
            self.say("Saved. Open it from your file manager to install: " + path)
            return
        try:
            if not self.can_install():
                self._pending_install = path
                self.popup("Allow installs",
                           "Android needs your permission before My Store can install apps.\n\n"
                           "Tap Open settings, switch on [b]Allow from this source[/b], then come back. "
                           "The install continues by itself.",
                           yes=self.open_install_settings, yes_label="Open settings")
                return
            self.launch_installer(path)
        except Exception:
            self.say("Saved. Open it from your file manager to install: " + path)

    def copy_to_downloads(self, path):
        """Android 10+: put a copy in the shared Downloads folder so the installer may read it."""
        from jnius import autoclass
        ContentValues = autoclass("android.content.ContentValues")
        Downloads = autoclass("android.provider.MediaStore$Downloads")
        Activity = autoclass("org.kivy.android.PythonActivity").mActivity
        values = ContentValues()
        values.put("_display_name", os.path.basename(path))
        values.put("mime_type", "application/vnd.android.package-archive")
        values.put("relative_path", "Download/My Store")
        resolver = Activity.getContentResolver()
        uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
        out = resolver.openOutputStream(uri)
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 16)
                    if not chunk:
                        break
                    out.write(bytearray(chunk))
        finally:
            out.close()
        return uri

    def launch_installer(self, path):
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        File = autoclass("java.io.File")
        Activity = autoclass("org.kivy.android.PythonActivity").mActivity
        if autoclass("android.os.Build$VERSION").SDK_INT >= 29:
            uri = self.copy_to_downloads(path)
        else:
            autoclass("android.os.StrictMode").disableDeathOnFileUriExposure()
            uri = Uri.fromFile(File(path))
        i = Intent(Intent.ACTION_VIEW)
        i.setDataAndType(uri, "application/vnd.android.package-archive")
        i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION)
        Activity.startActivity(i)

    def vote(self, app_id):
        if self.is_guest():
            self.need_login("share feedback")
            return
        body = {"device": self.device, "hash_ok": True, "works": True}
        tok = self.token()
        run_bg(lambda: call("/api/verify/%s" % app_id, body, tok),
               lambda d, e: (self.notice(e) if e else self.notice("Thanks, vote counted"),
                             self.load()))

    def report(self, app_id):
        if self.is_guest():
            self.need_login("report an app")
            return
        body = {"device": self.device, "reason": "reported from app"}
        tok = self.token()
        run_bg(lambda: call("/api/report/%s" % app_id, body, tok),
               lambda d, e: self.notice(e if e else "Reported. Thanks."))

    # ============================================================ settings tab
    def group(self, col, title):
        col.add_widget(text("[b]%s[/b]" % title, size="12sp", color=SUB, height=dp(22)))
        g = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(6), spacing=dp(2))
        g.bind(minimum_height=g.setter("height"))
        paint(g, CARD_D, 18)
        col.add_widget(g)
        return g

    def row(self, g, title, sub, action=None, danger=False):
        c = "ff6b6b" if danger else "eef2ff"
        label = "[b][color=%s]%s[/color][/b]" % (c, esc(title))
        if sub:
            label += "\n[size=12sp][color=93a0cc]%s[/color][/size]" % esc(sub)
        b = Button(text=label, markup=True, size_hint_y=None, height=dp(58 if sub else 48),
                   background_normal="", background_down="", background_color=(0, 0, 0, 0),
                   halign="left", valign="middle", font_size="14sp", padding_x=dp(12))
        b.bind(size=lambda i, v: setattr(i, "text_size", (v[0], v[1])))
        if action:
            b.bind(on_release=lambda *a: action())
        g.add_widget(b)

    def toggle_row(self, g, title, sub, key):
        r = BoxLayout(size_hint_y=None, height=dp(58), padding=[dp(12), 0, dp(6), 0], spacing=dp(8))
        r.add_widget(text("[b]%s[/b]\n[size=12sp][color=93a0cc]%s[/color][/size]" % (esc(title), esc(sub)),
                          size="14sp", color=TXT))
        on = P[key]
        btn = pill("ON" if on else "OFF", LINE_D, CYAN if on else SUB, h=32, size="12sp")
        holder = AnchorLayout(size_hint_x=None, width=dp(70))

        def flip(*a):
            P[key] = not P[key]
            save_prefs()
            btn.text = "ON" if P[key] else "OFF"
            btn.color = CYAN if P[key] else SUB
            if key in ("show_mods", "show_external") and self.items is not None:
                self.render()
            if key == "notify_updates":
                self.sync_service()
        btn.bind(on_release=flip)
        holder.add_widget(btn)
        r.add_widget(holder)
        g.add_widget(r)

    def build_settings(self):
        acct = self.active() or {"name": "Guest", "email": "Browsing as guest"}
        guest = self.active() is None
        sv = vscroll()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10),
                        padding=[dp(12), dp(12), dp(12), dp(24)])
        col.bind(minimum_height=col.setter("height"))

        # profile card
        prof = BoxLayout(size_hint_y=None, height=dp(100), padding=dp(16), spacing=dp(14))
        paint_grad(prof, (0.10, 0.36, 0.86, 1), (0.52, 0.26, 0.92, 1), 22)
        prof.add_widget(avatar(acct["name"], 62))
        who = BoxLayout(orientation="vertical", spacing=dp(2))
        who.add_widget(text("[b]%s[/b]" % esc(acct["name"]), size="18sp", color=WHITE,
                            height=dp(26), shorten=True))
        who.add_widget(text(esc(acct["email"]), size="13sp", color=(1, 1, 1, 0.85),
                            height=dp(20), shorten=True))
        prof.add_widget(who)
        col.add_widget(prof)

        g = self.group(col, "ACCOUNT")
        if guest:
            self.row(g, "Sign in or create account", "Needed to install apps and share feedback",
                     lambda: self.show_auth("signin", can_cancel=True))
        else:
            self.row(g, "Edit display name", acct["name"], self.edit_name)
            if acct.get("provider") != "google":
                self.row(g, "Change password", "Signs out your other devices", self.change_password)
            self.row(g, "Switch account", "%d on this phone" % len(P["accounts"]), self.switch_popup)
            self.row(g, "Add another account", "Sign in or create a new account",
                     lambda: self.show_auth("signin", can_cancel=True))
            self.row(g, "Sign out", "", lambda: self.popup(
                "Sign out?", "You can sign back in any time.", yes=self.sign_out, yes_label="Sign out"))

        g = self.group(col, "STORE PREFERENCES")
        self.toggle_row(g, "Warn about unverified apps", "Ask before installing", "warn_unverified")
        self.toggle_row(g, "Ask me to verify", "After an install finishes", "ask_verify")
        self.toggle_row(g, "Show modded apps", "Unofficial versions", "show_mods")
        self.toggle_row(g, "Show other stores' apps", "Apps linked from other sources", "show_external")
        self.row(g, "Default sort", "Popular" if P["sort"] == "popular" else "Newest", self.cycle_sort)

        info = getattr(self, "self_info", None)
        if info:
            g = self.group(col, "MY STORE UPDATE")
            self.row(g, "Update My Store to %s" % info["version"],
                     info.get("notes") or "Tap to download and install the new version", self.update_self)

        g = self.group(col, "NOTIFICATIONS")
        self.toggle_row(g, "App alerts", "Tell me about new apps and updates to apps I installed",
                        "notify_updates")
        self.row(g, "Send a test notification", "Check that alerts reach you",
                 lambda: self.notify("My Store", "Notifications are working."))

        g = self.group(col, "DOWNLOADS")
        self.row(g, "Download folder", save_dir(), lambda: self.text_popup("Download folder", save_dir()))
        self.row(g, "Clear downloaded APKs", "%d files" % len(P["downloads"]), self.clear_downloads)

        g = self.group(col, "SERVER")
        self.row(g, "Store server", SERVER.replace("https://", ""))

        if not guest and (P.get("dev_unlocked") or not HIDE_PUBLISH_REQUEST):
            g = self.group(col, "PUBLISH AN APP")
            self.row(g, "Request to publish an app", "For apps you can't put on Google Play",
                     self.publish_form)
            self.row(g, "My requests", "See if they were approved", self.my_requests)

        g = self.group(col, "ABOUT & LEGAL")
        for key, title, body in POLICIES:
            self.row(g, title, "", lambda t=title, b=body: self.policy_page(t, b))
        self.row(g, "My Store", "Version %s%s" % (APP_VERSION, "  -  update available" if getattr(self, "self_info", None) else ""), self.version_tap)

        if not guest:
            g = self.group(col, "DANGER ZONE")
            self.row(g, "Delete account", "Permanently removes your account and votes",
                     self.delete_account, danger=True)

        sv.add_widget(col)
        return sv

    # ---- settings actions
    def edit_name(self):
        acct = self.active()

        def submit(vals, msg, pop):
            name = vals[0].strip()
            if not name:
                msg.text = "Enter a display name"
                return
            tok = self.token()
            msg.text = "Saving..."

            def done(res, err):
                if err:
                    msg.text = err
                    return
                acct["name"] = res["user"]["name"]
                save_prefs()
                pop.dismiss()
                self.switch_tab("settings")
            run_bg(lambda: call("/api/me/update", {"name": name}, tok), done)
        self.form_popup("Display name", "", [("Display name", False, acct["name"])], "Save", submit)

    def change_password(self):
        def submit(vals, msg, pop):
            old, new, new2 = vals
            if len(new) < 8:
                msg.text = "New password must be at least 8 characters"
                return
            if new != new2:
                msg.text = "New passwords do not match"
                return
            tok = self.token()
            msg.text = "Saving..."

            def done(res, err):
                if err:
                    msg.text = err
                    return
                pop.dismiss()
                self.notice("Password changed")
            run_bg(lambda: call("/api/me/password", {"old": old, "new": new}, tok), done)
        self.form_popup("Change password", "",
                        [("Current password", True, ""), ("New password (8+)", True, ""),
                         ("Confirm new password", True, "")], "Change", submit)

    def switch_popup(self):
        box = BoxLayout(orientation="vertical", spacing=dp(8))
        pop = Dialog(title="Switch account", content=box, size_hint=(0.92, 0.6))
        sv = ScrollView()
        lst = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        lst.bind(minimum_height=lst.setter("height"))
        for a in P["accounts"]:
            cur = a["email"] == P["active"]
            b = pill("%s  (%s)%s" % (a["name"], a["email"], "  - current" if cur else ""),
                     ACCENT if cur else CHIP_BG, WHITE if cur else DARK, h=48, size="13sp",
                     bold=cur)
            b.bind(on_release=lambda i, em=a["email"]: (pop.dismiss(), self.switch_to(em)))
            lst.add_widget(b)
        sv.add_widget(lst)
        box.add_widget(sv)
        add = gpill("Add another account", BLUE_A, BLUE_B, h=46, size="14sp")
        add.bind(on_release=lambda *a: (pop.dismiss(), self.show_auth("signin", can_cancel=True)))
        box.add_widget(add)
        pop.open()

    def switch_to(self, email):
        P["active"] = email
        save_prefs()
        if P["accepted"].get(email) == TERMS_VERSION:
            self.show_main()
        else:
            self.show_terms(email, self.show_main, back=lambda: self.show_auth())

    def sign_out(self):
        acct = self.active()
        if acct:
            tok = acct["token"]
            run_bg(lambda: call("/api/logout", {}, tok), lambda r, e: None)
        self.drop_active("")

    def drop_active(self, message):
        P["accounts"] = [a for a in P["accounts"] if a["email"] != P["active"]]
        if P["accounts"]:
            P["active"] = P["accounts"][0]["email"]
            save_prefs()
            self.show_main()
        else:
            P["active"] = ""
            save_prefs()
            self.show_auth("signin", message=message)

    def delete_account(self):
        google = (self.active() or {}).get("provider") == "google"

        def submit(vals, msg, pop):
            if not vals[0]:
                msg.text = "Type DELETE to confirm" if google else "Enter your password"
                return
            tok = self.token()
            msg.text = "Deleting..."

            def done(res, err):
                if err:
                    msg.text = err
                    return
                pop.dismiss()
                self.drop_active("Account deleted")
            payload = {"confirm": vals[0]} if google else {"password": vals[0]}
            run_bg(lambda: call("/api/me/delete", payload, tok), done)
        self.form_popup("Delete account",
                        "This permanently deletes your account and your verification votes. "
                        + ("Type DELETE to confirm." if google else "Enter your password to confirm."),
                        [("Type DELETE" if google else "Password", not google, "")], "Delete", submit)

    def cycle_sort(self):
        P["sort"] = "new" if P["sort"] == "popular" else "popular"
        save_prefs()
        self.switch_tab("settings")

    def clear_downloads(self):
        n = 0
        for p in P["downloads"]:
            try:
                os.remove(p)
                n += 1
            except Exception:
                pass
        P["downloads"] = []
        save_prefs()
        self.notice("Removed %d files" % n)
        self.switch_tab("settings")

    def version_tap(self):
        if P.get("dev_unlocked") or not HIDE_PUBLISH_REQUEST:
            return
        now = time.time()
        if now - getattr(self, "_tap_time", 0) > 2:
            self._taps = 0
        self._tap_time = now
        self._taps = getattr(self, "_taps", 0) + 1
        if self._taps >= 7:
            self._taps = 0
            P["dev_unlocked"] = True
            save_prefs()
            self.notice("Publish option unlocked")
            self.switch_tab("settings")
        elif self._taps >= 4:
            self.notice("%d more taps..." % (7 - self._taps))

    def back_to_settings(self):
        self.show_main()
        self.switch_tab("settings")

    def publish_form(self):
        acct = self.active() or {"email": ""}
        sv = vscroll()
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10),
                        padding=[dp(16), dp(20), dp(16), dp(28)])
        col.bind(minimum_height=col.setter("height"))
        col.add_widget(text("[b]Request to publish an app[/b]", size="20sp", height=dp(36)))
        col.add_widget(auto_text("Every request is reviewed before it appears in the store. "
                                 "Only send apps you own or have permission to share.",
                                 size="13sp", color=GRAY))
        state = {"kind": "original", "rights": False}

        kind_btn = pill("Type: Original app", CHIP_BG, DARK, h=44)

        def flip_kind(*a):
            state["kind"] = "mod" if state["kind"] == "original" else "original"
            kind_btn.text = "Type: Modded version" if state["kind"] == "mod" else "Type: Original app"
        kind_btn.bind(on_release=flip_kind)
        col.add_widget(kind_btn)

        box, name_in = field("App name")
        col.add_widget(box)
        box, ver_in = field("Version (e.g. 1.2.0)")
        col.add_widget(box)
        box, cat_in = field("Category (e.g. Games, Tools)")
        col.add_widget(box)
        box, mod_in = field("Modded version of which app? (mods only)")
        col.add_widget(box)
        box, pkg_in = field("Package name (optional, e.g. com.company.app)")
        col.add_widget(box)
        box, url_in = field("Download link (https://...)")
        col.add_widget(box)
        box, desc_in = area("What does the app do? What is changed in this version?")
        col.add_widget(box)
        box, why_in = area("Why is it not on Google Play?", h=90)
        col.add_widget(box)
        box, contact_in = field("Your contact (email or Telegram)", default=acct["email"])
        col.add_widget(box)

        col.add_widget(auto_text("I own this app, or its owner or license lets me share it. It has no "
                                 "malware, and it is not a paid app with the payment removed.",
                                 size="12sp", color=GRAY))
        rights = pill("I confirm", CHIP_BG, DARK, h=40, bold=False)

        def flip_rights(inst):
            state["rights"] = not state["rights"]
            inst.text = "Confirmed" if state["rights"] else "I confirm"
            inst.color = ACCENT if state["rights"] else DARK
            inst.bold = state["rights"]
        rights.bind(on_release=flip_rights)
        col.add_widget(rights)

        err = text("", size="13sp", color=RED, height=dp(36))
        col.add_widget(err)
        send = pill("Send request", ACCENT, WHITE, h=52, size="16sp")

        def submit(*a):
            if not state["rights"]:
                err.color = RED
                err.text = "Please confirm you have the right to share this app"
                return
            payload = {
                "name": name_in.text.strip(), "version": ver_in.text.strip(),
                "category": cat_in.text.strip(), "kind": state["kind"],
                "mod_of": mod_in.text.strip(), "package": pkg_in.text.strip(),
                "description": desc_in.text.strip(), "url": url_in.text.strip(),
                "reason": why_in.text.strip(), "contact": contact_in.text.strip(),
                "rights": True}
            tok = self.token()
            err.color = GRAY
            err.text = "Sending..."

            def done(res, e):
                if e:
                    err.color = RED
                    err.text = esc(e)
                    return
     
