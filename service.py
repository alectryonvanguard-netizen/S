import os
import ssl
import json
import time
from urllib.request import urlopen, Request

HERE = os.path.dirname(os.path.abspath(__file__))
PREFS_PATH = os.path.join(HERE, "store_prefs.json")      # written by the app (we only read it)
STATE_PATH = os.path.join(HERE, "update_state.json")     # written by this service
CHECK_EVERY = 30 * 60                                    # seconds

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def fetch_apps(server):
    req = Request(server.rstrip("/") + "/api/apps", headers={"User-Agent": "MyStore-service"})
    with urlopen(req, timeout=20, context=CTX) as r:
        return json.loads(r.read().decode())


def check(notify):
    """Call notify(title, message, id) once for every new version of an app that was installed."""
    prefs = load_json(PREFS_PATH, {})
    tracked = prefs.get("tracked") or {}
    if not prefs.get("notify_updates", True) or not tracked or not prefs.get("server"):
        return 0
    apps = {str(a["id"]): a for a in fetch_apps(prefs["server"])}
    state = load_json(STATE_PATH, {})
    sent = 0
    for app_id, info in tracked.items():
        a = apps.get(app_id)
        if not a or "play.google.com" in (a.get("url") or ""):
            continue
        version = str(a.get("version") or "")
        if version and version != str(info.get("version")) and state.get(app_id) != version:
            notify("Update available",
                   "%s %s is ready (you have %s)" % (a["name"], version, info.get("version")),
                   2000 + int(app_id) % 1000)
            state[app_id] = version
            sent += 1
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception:
        pass
    return sent


def run():
    from jnius import autoclass
    from store_notify import post_notification
    context = autoclass("org.kivy.android.PythonService").mService

    def notify(title, message, notif_id):
        post_notification(context, title, message, notif_id)

    time.sleep(20)                                       # let the phone settle after start
    while True:
        try:
            check(notify)
        except Exception:
            pass                                         # no signal right now: try again later
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    run()
