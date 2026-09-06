# Android entry points and FileProvider are created by the platform.
-keep class * extends android.app.Activity { *; }
-keep class * extends android.app.Service { *; }
-keep class * extends android.app.BroadcastReceiver { *; }
-keep class * extends android.app.ContentProvider { *; }

# Zenbo Robot Framework is supplied as a local SDK and invokes API surfaces
# reflectively on physical robots. Keep the SDK implementation intact.
-keep class com.asus.robotframework.** { *; }
-dontwarn com.asus.robotframework.**

# MQTT Paho uses reflection for selected network and logging internals.
-keep class org.eclipse.paho.** { *; }
-dontwarn org.eclipse.paho.**

# Gson reflection: keep all model and DTO classes, fields, and constructors intact
-keepattributes Signature,*Annotation*,InnerClasses,EnclosingMethod
-keep class com.google.gson.** { *; }
-keep class com.hackathon.zenboclient.model.** { *; }
-keepclassmembers class com.hackathon.zenboclient.model.** { *; }
-keepclassmembers class * {
  @com.google.gson.annotations.SerializedName <fields>;
}

# Keep all Zenbo client components
-keep class com.hackathon.zenboclient.** { *; }
-keepclassmembers class com.hackathon.zenboclient.** { *; }
