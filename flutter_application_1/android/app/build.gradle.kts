plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.flutter_application_1"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17

        // 【这一行是 flutter_local_notifications 要求的，不是可选项】
        // 不开的话 `flutter build apk` 会直接失败在 checkDebugAarMetadata：
        //   "Dependency ':flutter_local_notifications' requires core library
        //    desugaring to be enabled for :app."
        //
        // 【它在做什么】Android 的旧版本（API < 26）里没有 java.time 这些
        // Java 8 的日期时间类。通知插件要用它们来算「什么时候该弹」，
        // 所以构建期需要把这些调用改写成等价的老 API 实现 —— 这就是脱糖。
        //
        // 【为什么 B0 装依赖时没发现】因为 `flutter pub add` 和 `flutter analyze`
        // 都**不碰 Android 构建**，只有真的编 APK 才会走到这一步。
        // 这正是「依赖闸门必须在写业务代码前真的构建一次」的教训。
        isCoreLibraryDesugaringEnabled = true
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.example.flutter_application_1"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

dependencies {
    // 配合上面的 isCoreLibraryDesugaringEnabled —— 这一条提供脱糖用的实现库。
    // 【版本选择】2.1.4 是当前稳定线，要求 AGP 8.x（本项目用的就是 8.x）。
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}
