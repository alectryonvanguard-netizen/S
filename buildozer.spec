[app]
title = My Store
package.name = mystore
package.domain = org.mystore
source.dir = .
source.include_exts = py,png,jpg,jpeg,json
version = 1.0

requirements = python3,kivy==2.3.0,pyjnius,android,certifi

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #050816

orientation = portrait
fullscreen = 0

android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.build_tools_version = 33.0.2

p4a.branch = v2024.01.21

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,REQUEST_INSTALL_PACKAGES,POST_NOTIFICATIONS,FOREGROUND_SERVICE

# lets the Google sign-in page send you back to the app (mystore://auth)
android.manifest.intent_filters = intent_filters.xml

# background checker that sends "update available" notifications
services = updates:service.py:foreground

[buildozer]
log_level = 2
warn_on_root = 1
