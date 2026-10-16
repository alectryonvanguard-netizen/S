[app]
title = My Store
package.name = mystore
package.domain = org.mystore
source.dir = .
source.include_exts = py,png,jpg,json
version = 1.0
requirements = python3,kivy,pyjnius,android
android.ndk=27.3.13750724
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,REQUEST_INSTALL_PACKAGES
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
