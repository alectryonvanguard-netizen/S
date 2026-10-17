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
from urllib.parse import quote
from urllib.error import HTTPError

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.label import Label
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

SERVER = "https://sam202411.pythonanywhere.com"
APP_VERSION = "1.0"
TERMS_VERSION = "2026-10"
SESSION_EXPIRED = "Session expired"
SPLASH_SECONDS = 5     # how long the loading screen stays
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
            "dev_unlocked": False, "guest": False}


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
        accs.append({"email": email, "name": u["name"], "token": res["token"]})
        P["accounts"] = accs
        P["active"] = email
        P["guest"] = False
        save_prefs()

    def notice(self, msg):
        pop = Popup(title="", content=text(esc(msg), color=WHITE, halign="center"),
                    size_hint=(0.8, 0.16), separator_height=0)
        pop.open()
        Clock.schedule_once(lambda dt: pop.dismiss(), 1.8)

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

        sv = ScrollView(bar_width=dp(3))
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
        nav = BoxLayout(size_hint_y=None, height=dp(58), padding=[dp(10), dp(6)], spacing=dp(8))
        paint(nav, WHITE, [18, 18, 0, 0])
        self.nav_btns = {}
        for key, label in (("store", "Store"), ("settings", "Settings")):
            b = Button(text=label, background_normal="", background_down="",
                       background_color=(0, 0, 0, 0), font_size="15sp")
            b.bind(on_release=lambda i, k=key: self.switch_tab(k))
            self.nav_btns[key] = b
            nav.add_widget(b)
        col = BoxLayout(orientation="vertical")
        col.add_widget(self.content)
        col.add_widget(nav)
        self.show(col)
        self.switch_tab("store")
        self.load()

    def switch_tab(self, key):
        self.content.clear_widgets()
        self.content.add_widget(self.store_view if key == "store" else self.build_settings())
        self.tab = key
        for k, b in self.nav_btns.items():
            b.color = ACCENT if k == key else GRAY
            b.bold = (k == key)

    # ============================================================ store tab
    def build_store(self):
        self.kind, self.cat = "", ""
        self.sort = P["sort"]
        view = BoxLayout(orientation="vertical", spacing=dp(6))

        header = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(134),
                           padding=[dp(14), dp(12), dp(14), dp(14)], spacing=dp(8))
        paint(header, HEADER, [0, 0, 26, 26])
        trow = BoxLayout(size_hint_y=None, height=dp(40))
        trow.add_widget(text("[b]My Store[/b]", size="22sp", color=WHITE))
        acct = self.active()
        av = Button(text=esc((acct["name"] if acct else "G")[:1].upper()), size_hint=(None, None),
                    size=(dp(38), dp(38)), background_normal="", background_down="",
                    background_color=(0, 0, 0, 0), color=ACCENT, bold=True, font_size="16sp")
        paint(av, WHITE, 19)
        av.bind(on_release=lambda *a: self.switch_tab("settings"))
        trow.add_widget(av)
        header.add_widget(trow)

        bar = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(4), 0], spacing=dp(2))
        paint(bar, WHITE, 24)
        self.search = TextInput(hint_text="Search apps, games, developers", multiline=False,
                                background_normal="", background_active="",
                                background_color=(0, 0, 0, 0), foreground_color=DARK,
                                hint_text_color=(0.55, 0.57, 0.62, 1), cursor_color=ACCENT,
                                padding=[dp(14), dp(14), dp(4), dp(10)])
        self.search.bind(text=self.on_search_text)
        clear = Button(text="X", size_hint_x=None, width=dp(44), background_normal="",
                       background_down="", background_color=(0, 0, 0, 0), color=GRAY, bold=True)
        clear.bind(on_release=lambda *a: setattr(self.search, "text", ""))
        bar.add_widget(self.search)
        bar.add_widget(clear)
        header.add_widget(bar)
        view.add_widget(header)

        self.kind_row = self.make_chip_row()
        self.cat_row = self.make_chip_row()
        view.add_widget(self.kind_row[0])
        view.add_widget(self.cat_row[0])
        self.refresh_kinds()

        srow = BoxLayout(size_hint_y=None, height=dp(34), padding=[dp(14), 0])
        self.status = text("Starting...", size="12sp", color=GRAY)
        self.sort_btn = pill("Sort: Popular" if self.sort == "popular" else "Sort: Newest",
                             CHIP_BG, DARK, h=30, size="12sp", bold=False)
        self.sort_btn.size_hint_x = None
        self.sort_btn.width = dp(120)
        self.sort_btn.bind(on_release=lambda *a: self.toggle_sort())
        srow.add_widget(self.status)
        srow.add_widget(self.sort_btn)
        view.add_widget(srow)

        scroll = ScrollView(bar_width=dp(3))
        self.box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10),
                             padding=[dp(12), dp(4), dp(12), dp(16)])
        self.box.bind(minimum_height=self.box.setter("height"))
        scroll.add_widget(self.box)
        view.add_widget(scroll)
        return view

    def make_chip_row(self):
        sv = ScrollView(size_hint_y=None, height=dp(42), do_scroll_y=False, bar_width=0)
        inner = BoxLayout(size_hint_x=None, spacing=dp(8), padding=[dp(12), dp(3)])
        inner.bind(minimum_width=inner.setter("width"))
        sv.add_widget(inner)
        return sv, inner

    def chip(self, label, active, action):
        b = Button(text=esc(label), size_hint=(None, 1), width=dp(30) + dp(8) * len(label),
                   background_normal="", background_down="", background_color=(0, 0, 0, 0),
                   color=WHITE if active else DARK, font_size="13sp", bold=active)
        paint(b, ACCENT if active else CHIP_BG, 18)
        b.bind(on_release=lambda *a: action())
        return b

    def refresh_kinds(self):
        inner = self.kind_row[1]
        inner.clear_widgets()
        for label, kind in (("All", ""), ("Originals", "original"),
                            ("Mods", "mod"), ("Other stores", "external")):
            inner.add_widget(self.chip(label, self.kind == kind, lambda k=kind: self.set_kind(k)))

    def refresh_cats(self):
        inner = self.cat_row[1]
        inner.clear_widgets()
        cats = sorted({a["category"] for a in self.data if a.get("category")})
        inner.add_widget(self.chip("All categories", self.cat == "", lambda: self.set_cat("")))
        for c in cats:
            inner.add_widget(self.chip(c, self.cat == c, lambda x=c: self.set_cat(x)))

    def on_search_text(self, inst, value):
        if self._ev:
            self._ev.cancel()
        self._ev = Clock.schedule_once(lambda dt: self.load(), 0.5)

    def set_kind(self, kind):
        self.kind = kind
        self.cat = ""
        self.refresh_kinds()
        self.load()

    def set_cat(self, cat):
        self.cat = cat
        self.refresh_cats()
        self.render()

    def toggle_sort(self):
        self.sort = "new" if self.sort == "popular" else "popular"
        self.sort_btn.text = "Sort: Popular" if self.sort == "popular" else "Sort: Newest"
        self.render()

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
            return
        self.data = data
        if self.cat and self.cat not in {a.get("category") for a in data}:
            self.cat = ""
        self.refresh_cats()
        self.render()

    def render(self):
        self.box.clear_widgets()
        rows = [a for a in self.data
                if (not self.cat or a.get("category") == self.cat)
                and (P["show_mods"] or a["kind"] != "mod")
                and (P["show_external"] or a["kind"] != "external")]
        if self.sort == "popular":
            rows.sort(key=lambda a: a.get("downloads", 0), reverse=True)
        else:
            rows.sort(key=lambda a: a.get("id", 0), reverse=True)
        self.items = {a["id"]: a for a in self.data}
        if not rows:
            self.box.add_widget(text("No apps found", size="16sp", color=GRAY,
                                     height=dp(120), halign="center"))
        for a in rows:
            self.box.add_widget(self.card(a))
        self.say("%d apps" % len(rows))

    def card(self, a):
        name = a["name"]
        color = ICON_COLORS[sum(ord(c) for c in name) % len(ICON_COLORS)]
        if is_store_link(a):
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

        card = BoxLayout(size_hint_y=None, height=dp(124), padding=dp(12), spacing=dp(12))
        paint(card, WHITE, 18)
        card.add_widget(avatar(name, 62, bg=color, fg=WHITE))

        info = BoxLayout(orientation="vertical", spacing=dp(2))
        info.add_widget(text("[b]%s[/b]" % esc(name), size="16sp", height=dp(24), shorten=True))
        info.add_widget(text("%s  -  %s" % (esc(a["developer"]), esc(a["category"])),
                             size="12sp", color=GRAY, height=dp(18), shorten=True))
        info.add_widget(text("%s downloads  -  v%s" % (a["downloads"], esc(a["version"])),
                             size="12sp", color=GRAY, height=dp(18), shorten=True))
        info.add_widget(text(badge, size="12sp"))
        card.add_widget(info)

        side = AnchorLayout(size_hint_x=None, width=dp(88))
        col = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(78), spacing=dp(6))
        inst = pill("Open" if is_store_link(a) else "Install", ACCENT, WHITE)
        inst.bind(on_release=lambda *x, i=a["id"]: self.get_app(i))
        det = pill("Details", CHIP_BG, DARK, h=34, size="12sp", bold=False)
        det.bind(on_release=lambda *x, i=a["id"]: self.details(i))
        col.add_widget(inst)
        col.add_widget(det)
        side.add_widget(col)
        card.add_widget(side)
        return card

    # ============================================================ popups
    def popup(self, title, msg, yes=None, yes_label="Continue", extra=None):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        sv = ScrollView()
        sv.add_widget(auto_text(msg, size="14sp", color=WHITE))
        box.add_widget(sv)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        pop = Popup(title=title, content=box, size_hint=(0.92, 0.62))
        close = Button(text="Cancel" if yes else "Close")
        close.bind(on_release=lambda *a: pop.dismiss())
        row.add_widget(close)
        if extra:
            b = Button(text=extra[0])
            b.bind(on_release=lambda *a: (pop.dismiss(), extra[1]()))
            row.add_widget(b)
        if yes:
            ok = Button(text=yes_label, background_normal="", background_color=ACCENT)
            ok.bind(on_release=lambda *a: (pop.dismiss(), yes()))
            row.add_widget(ok)
        box.add_widget(row)
        pop.open()

    def form_popup(self, title, intro, fields, submit_label, on_submit):
        """fields: [(hint, is_password, default)]. on_submit(values, msg_label, popup)."""
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        if intro:
            box.add_widget(auto_text(intro, size="13sp", color=WHITE))
        inputs = []
        for hint, pw, default in fields:
            b, ti = field(hint, pw, default)
            box.add_widget(b)
            inputs.append(ti)
        msg = text("", size="12sp", color=(1, 0.55, 0.55, 1), height=dp(32))
        box.add_widget(msg)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        pop = Popup(title=title, content=box, size_hint=(0.94, None),
                    height=dp(210 + 62 * len(fields) + (50 if intro else 0)))
        cancel = Button(text="Cancel")
        cancel.bind(on_release=lambda *a: pop.dismiss())
        go = Button(text=submit_label, background_normal="", background_color=ACCENT)
        go.bind(on_release=lambda *a: on_submit([i.text for i in inputs], msg, pop))
        row.add_widget(cancel)
        row.add_widget(go)
        box.add_widget(row)
        pop.open()

    def text_popup(self, title, body):
        self.popup(title, esc(body))

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
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            Activity = autoclass("org.kivy.android.PythonActivity")
            i = Intent(Intent.ACTION_VIEW, Uri.parse(a["url"]))
            i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            Activity.mActivity.startActivity(i)
        except Exception:
            try:
                import webbrowser
                webbrowser.open(a["url"])
            except Exception:
                self.say("Open this link in your browser: " + a["url"])

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
        save_prefs()
        self.say("Saved: " + path)
        self.try_install(path)
        if P["ask_verify"]:
            self.popup("Did it install and work?",
                       "If yes, you can help verify this app (one vote per account).",
                       yes=lambda: self.vote(a["id"]), yes_label="Yes, verify")

    def try_install(self, path):
        try:
            from jnius import autoclass
            autoclass("android.os.StrictMode").disableDeathOnFileUriExposure()
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            File = autoclass("java.io.File")
            Activity = autoclass("org.kivy.android.PythonActivity")
            i = Intent(Intent.ACTION_VIEW)
            i.setDataAndType(Uri.fromFile(File(path)), "application/vnd.android.package-archive")
            i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            Activity.mActivity.startActivity(i)
        except Exception:
            self.say("Saved. Open it from your file manager to install: " + path)

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
        col.add_widget(text("[b]%s[/b]" % title, size="12sp", color=GRAY, height=dp(22)))
        g = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(6), spacing=dp(2))
        g.bind(minimum_height=g.setter("height"))
        paint(g, WHITE, 18)
        col.add_widget(g)
        return g

    def row(self, g, title, sub, action=None, danger=False):
        c = "e53935" if danger else "1f2230"
        label = "[b][color=%s]%s[/color][/b]" % (c, esc(title))
        if sub:
            label += "\n[size=12sp][color=7a7f8c]%s[/color][/size]" % esc(sub)
        b = Button(text=label, markup=True, size_hint_y=None, height=dp(58 if sub else 48),
                   background_normal="", background_down="", background_color=(0, 0, 0, 0),
                   halign="left", valign="middle", font_size="14sp", padding_x=dp(12))
        b.bind(size=lambda i, v: setattr(i, "text_size", (v[0], v[1])))
        if action:
            b.bind(on_release=lambda *a: action())
        g.add_widget(b)

    def toggle_row(self, g, title, sub, key):
        r = BoxLayout(size_hint_y=None, height=dp(58), padding=[dp(12), 0, dp(6), 0], spacing=dp(8))
        r.add_widget(text("[b]%s[/b]\n[size=12sp][color=7a7f8c]%s[/color][/size]" % (esc(title), esc(sub)),
                          size="14sp"))
        on = P[key]
        btn = pill("ON" if on else "OFF", CHIP_BG, ACCENT if on else GRAY, h=32, size="12sp")
        holder = AnchorLayout(size_hint_x=None, width=dp(70))

        def flip(*a):
            P[key] = not P[key]
            save_prefs()
            btn.text = "ON" if P[key] else "OFF"
            btn.color = ACCENT if P[key] else GRAY
            if key in ("show_mods", "show_external") and self.items is not None:
                self.render()
        btn.bind(on_release=flip)
        holder.add_widget(btn)
        r.add_widget(holder)
        g.add_widget(r)

    def build_settings(self):
        acct = self.active() or {"name": "Guest", "email": "Browsing as guest"}
        guest = self.active() is None
        sv = ScrollView(bar_width=dp(3))
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10),
                        padding=[dp(12), dp(12), dp(12), dp(24)])
        col.bind(minimum_height=col.setter("height"))

        # profile card
        prof = BoxLayout(size_hint_y=None, height=dp(100), padding=dp(16), spacing=dp(14))
        paint(prof, HEADER, 22)
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
            self.row(g, title, "", lambda t=title, b=body: self.text_popup(t, b))
        self.row(g, "My Store", "Version %s" % APP_VERSION, self.version_tap)

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
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        pop = Popup(title="Switch account", content=box, size_hint=(0.92, 0.6))
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
        add = Button(text="Add another account", size_hint_y=None, height=dp(46))
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
        def submit(vals, msg, pop):
            if not vals[0]:
                msg.text = "Enter your password"
                return
            tok = self.token()
            msg.text = "Deleting..."

            def done(res, err):
                if err:
                    msg.text = err
                    return
                pop.dismiss()
                self.drop_active("Account deleted")
            run_bg(lambda: call("/api/me/delete", {"password": vals[0]}, tok), done)
        self.form_popup("Delete account",
                        "This permanently deletes your account and your verification votes. "
                        "Enter your password to confirm.",
                        [("Password", True, "")], "Delete", submit)

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
        sv = ScrollView(bar_width=dp(3))
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
                self.notice("Request sent. We will review it.")
                self.back_to_settings()
            run_bg(lambda: call("/api/submit", payload, tok), done)
        send.bind(on_release=submit)
        col.add_widget(send)

        back = pill("Cancel", CHIP_BG, DARK, h=44, bold=False)
        back.bind(on_release=lambda *a: self.back_to_settings())
        col.add_widget(back)

        sv.add_widget(col)
        self.show(sv)

    def my_requests(self):
        tok = self.token()

        def done(rows, e):
            if e:
                self.popup("My requests", esc(e))
                return
            if not rows:
                self.popup("My requests", "You have not sent any requests yet.")
                return
            labels = {"pending": "Waiting for review", "approved": "Approved and published",
                      "rejected": "Not approved"}
            lines = []
            for r in rows:
                line = "[b]%s[/b]  v%s\n%s" % (esc(r["name"]), esc(r["version"]),
                                              labels.get(r["status"], esc(r["status"])))
                if r.get("note"):
                    line += "\n" + esc(r["note"])
                lines.append(line)
            self.popup("My requests", "\n\n".join(lines))
        run_bg(lambda: call("/api/submissions/mine", token=tok), done)


StoreApp().run()
