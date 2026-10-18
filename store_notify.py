import time


def post_notification(context, title, message, notif_id=None):
    from jnius import autoclass
    Context = autoclass("android.content.Context")
    Version = autoclass("android.os.Build$VERSION")
    NotificationManager = autoclass("android.app.NotificationManager")
    manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
    channel_id = "mystore_updates"
    if Version.SDK_INT >= 26:
        NotificationChannel = autoclass("android.app.NotificationChannel")
        manager.createNotificationChannel(
            NotificationChannel(channel_id, "App updates", NotificationManager.IMPORTANCE_DEFAULT))
        builder = autoclass("android.app.Notification$Builder")(context, channel_id)
    else:
        builder = autoclass("android.app.Notification$Builder")(context)
    builder.setSmallIcon(context.getApplicationInfo().icon)
    builder.setContentTitle(title)
    builder.setContentText(message)
    builder.setAutoCancel(True)
    try:                                      # tapping the notification opens My Store
        PendingIntent = autoclass("android.app.PendingIntent")
        Intent = autoclass("android.content.Intent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        open_app = Intent(context, PythonActivity)
        builder.setContentIntent(PendingIntent.getActivity(
            context, 0, open_app, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
    except Exception:
        pass
    manager.notify(notif_id if notif_id is not None else int(time.time()) % 100000, builder.build())
