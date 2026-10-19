# service.py - runs in the background and tells you when an app you installed has a new version.
import os
import ssl
import json
import time
from urllib.request import urlopen, Request

from store_notify import is_newer

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


def fetch_self(server):
    req = Request(server.rstrip("/") + "/api/self", headers={"User-Agent": "MyStore-service"})
    with urlopen(req, timeout=20, context=CTX) as r:
        return json.loads(r.read().decode())


def check(notify):
    """Call notify(title, message, id, kind, app_id) for new apps, app updates and My Store updates.
    Returns how many notifications were sent."""
    prefs = load_json(PREFS_PATH, {})
    if not prefs.get("notify_updates", True) or not prefs.get("server"):
        return 0
    apps = {str(a["id"]): a for a in fetch_apps(prefs["server"])}
    state = load_json(STATE_PATH, {})
    if "versions" not in state:                       # older state file: just version notes
        state = {"versions": {k: v for k, v in state.items() if isinstance(v, str)}, "seen": None}
    sent = 0

    # 1) apps that were added to the store since the last check
    seen = state.get("seen")
    if seen is None:                                  # first run: remember what is there, say nothing
        state["seen"] = sorted(apps)
    else:
        fresh = [a for k, a in apps.items() if k not in set(seen)]
        if len(fresh) == 1:
            notify("New app in My Store", "%s was just added" % fresh[0]["name"],
                   3000 + int(fresh[0]["id"]) % 1000, "new", fresh[0]["id"])
            sent += 1
        elif fresh:
            notify("New apps in My Store", "%d new apps were just added" % len(fresh), 3999, "new", None)
            sent += 1
        state["seen"] = sorted(set(seen) | set(apps))

    # 2) new versions of apps that were installed from My Store
    for app_id, info in (prefs.get("tracked") or {}).items():
        a = apps.get(app_id)
        if not a or "play.google.com" in (a.get("url") or ""):
            continue
        version = str(a.get("version") or "")
        if version and version != str(info.get("version")) and state["versions"].get(app_id) != version:
            notify("Update available",
                   "%s %s is ready (you have %s)" % (a["name"], version, info.get("version")),
                   2000 + int(app_id) % 1000, "update", a["id"])
            state["versions"][app_id] = version
            sent += 1

    # 3) a new version of My Store itself
    try:
        info = fetch_self(prefs["server"])
    except Exception:
        info = None
    installed = str(prefs.get("app_version") or "")
    if info and info.get("version") and info.get("url") and installed:
        if is_newer(info["version"], installed) and state.get("self") != info["version"]:
            notify("My Store update", "Version %s is ready. Open My Store > Profile to update." % info["version"],
                   4000, "self", None)
            state["self"] = info["version"]
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

    def notify(title, message, notif_id, kind="", app_id=None):
        post_notification(context, title, message, notif_id, kind=kind, app_id=app_id)

    time.sleep(20)                                       # let the phone settle after start
    while True:
        try:
            check(notify)
        except Exception:
            pass                                         # no signal right now: try again later
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    run()
