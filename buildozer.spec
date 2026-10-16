
[app]
title = My Store
package.name = mystore
package.domain = org.mystore
source.dir = .
source.include_exts = py,png,jpg,jpeg,json
version = 1.0

requirements = python3,kivy,pyjnius,android

orientation = portrait
fullscreen = 0

android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,REQUEST_INSTALL_PACKAGES

[buildozer]
log_level = 2
warn_on_root = 1
