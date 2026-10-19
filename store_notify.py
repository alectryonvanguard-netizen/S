# store_notify.py - notifications for My Store: the phone's notification bar plus an in-app inbox.
# Used by the app and by the background service.
import os
import re
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX_PATH = os.path.join(HERE, "inbox.json")
KINDS = {"new": "New app", "update": "App update", "self": "My Store update", "test": "Test"}


def read_inbox():
    try:
        with open(INBOX_PATH) as f:
            items = json.load(f)
        return [i for i in items if isinstance(i, dict)]
    except Exception:
        return []


def add_to_inbox(kind, title, message, app_id=None):
    items = read_inbox()
    items.insert(0, {"t": time.time(), "kind": kind, "title": title, "message": message, "app_id": app_id})
    try:
        with open(INBOX_PATH, "w") as f:
            json.dump(items[:50], f)
    except Exception:
        pass


def clear_inbox():
    try:
        os.remove(INBOX_PATH)
    except OSError:
        pass


def is_newer(new, old):
    """True when version `new` is higher than `old` (1.10 is newer than 1.9)."""
    a = tuple(int(x) for x in re.findall(r"\d+", str(new))) or (0,)
    b = tuple(int(x) for x in re.findall(r"\d+", str(old))) or (0,)
    return a > b


def post_notification(context, title, message, notif_id=None, kind="", app_id=None):
    """Show a notification that says what it is, and keep a copy in the in-app inbox."""
    if kind:
        add_to_inbox(kind, title, message, app_id)
    from jnius import autoclass
    Context = autoclass("android.content.Context")
    Version = autoclass("android.os.Build$VERSION")
    NotificationManager = autoclass("android.app.NotificationManager")
    manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
    channel_id = "mystore_updates"
    Builder = autoclass("android.app.Notification$Builder")
    if Version.SDK_INT >= 26:
        NotificationChannel = autoclass("android.app.NotificationChannel")
        manager.createNotificationChannel(
            NotificationChannel(channel_id, "App updates", NotificationManager.IMPORTANCE_DEFAULT))
        builder = Builder(context, channel_id)
    else:
        builder = Builder(context)
    nid = notif_id if notif_id is not None else int(time.time()) % 100000
    builder.setSmallIcon(context.getApplicationInfo().icon)
    builder.setContentTitle(title)
    builder.setContentText(message)
    if kind:
        builder.setSubText(KINDS.get(kind, kind))          # small label: New app / App update / My Store update
    try:                                                    # the whole message shows when expanded
        style = autoclass("android.app.Notification$BigTextStyle")()
        style.bigText(message)
        builder.setStyle(style)
    except Exception:
        pass
    builder.setAutoCancel(True)
    try:                                                    # tapping it opens My Store on the notifications page
        PendingIntent = autoclass("android.app.PendingIntent")
        Intent = autoclass("android.content.Intent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        open_app = Intent(context, PythonActivity)
        open_app.putExtra("open", "inbox")
        open_app.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
        builder.setContentIntent(PendingIntent.getActivity(
            context, nid, open_app, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
    except Exception:
        pass
    manager.notify(nid, builder.build())
