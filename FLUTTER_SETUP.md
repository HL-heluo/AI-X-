# Flutter 开发环境搭建报告

生成时间：2026-09-28
机器：DESKTOP-5D9VH53 / Windows 10 专业版 22H2 (19045.5247)

---

## 一、结论

Flutter 现在可以在 VS Code 中正常开发 **Android** 和 **Web** 应用。
**Windows 桌面** 构建还差一步需要管理员权限的操作（见第五节）。

已实测通过：
- `flutter build web` → 成功
- `flutter build apk --debug` → 成功产出 `app-debug.apk`（143.5 MB）

---

## 二、最终 flutter doctor 状态

```
[√] Flutter (Channel stable, 3.47.5, locale zh-CN)
[√] Windows Version (10 专业版 64 位, 22H2, 2009)
[√] Android toolchain - develop for Android devices (Android SDK version 36.0.0)
[√] Chrome - develop for the web
[!] Visual Studio - develop Windows apps (缺少 CMake 工具 + Windows 11 SDK)
[√] Connected device (3 available)
[!] Network resources (maven.google.com 不可达 —— 不影响实际构建)
```

---

## 三、已安装 / 已配置内容

### 1. Flutter SDK
| 项目 | 值 |
|---|---|
| 路径 | `G:\flutter\flutter` |
| 版本 | 3.47.5 stable（Dart 3.13.4，DevTools 2.60.0） |
| 备份压缩包 | `G:\flutter\flutter_windows_3.47.5-stable.zip`（1.93 GB，可删） |

SDK 之前已经解压好，只是没生效到环境里；**用户 PATH 中已经存在 `G:\flutter\flutter\bin`**，
新开的终端 / VS Code 终端可以直接使用 `flutter`、`dart` 命令。

### 2. JDK（Android 构建必需 17+，系统默认的 Java 16 太旧）
| 项目 | 值 |
|---|---|
| 路径 | `F:\Java21\jdk-21.0.12.1+1` |
| 版本 | Microsoft OpenJDK 21.0.12.1 LTS |
| 环境变量 | `JAVA_HOME`（用户级）|
| Flutter 配置 | `flutter config --jdk-dir F:\Java21\jdk-21.0.12.1+1` |

### 3. Android SDK
| 项目 | 值 |
|---|---|
| 根目录 | `F:\Android\Sdk` |
| 环境变量 | `ANDROID_HOME`、`ANDROID_SDK_ROOT`（用户级）|
| PATH 追加 | `platform-tools`、`cmdline-tools\latest\bin`、`emulator` |

已安装的包（许可证已全部接受）：
- `cmdline-tools` 20.0
- `platform-tools`（adb）
- `platforms;android-36`
- `build-tools;36.0.0`
- `ndk;28.2.13676358`（2.1 GB）

Flutter 3.47 默认 `compileSdk 36 / targetSdk 36 / minSdk 24 / ndk 28.2.13676358`，与上面完全对应。

### 4. Chrome（Web 调试用）
| 项目 | 值 |
|---|---|
| 路径 | `C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe` |
| 版本 | 154.0.8037.58（当前用户级安装，无需管理员）|

`flutter devices` 现在能看到 3 个设备：Windows (desktop)、Chrome (web)、Edge (web)。

### 5. VS Code
已安装扩展（此前就有）：
- `Dart-Code.dart-code`
- `Dart-Code.flutter`

在 `C:\Users\Administrator\AppData\Roaming\Code\User\settings.json` 中新增：
```jsonc
"dart.flutterSdkPath": "G:\\flutter\\flutter",
"dart.debugExternalPackageLibraries": false,
"dart.debugSdkLibraries": false,
"[dart]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "Dart-Code.dart-code",
    "editor.rulers": [80],
    "editor.selectionHighlight": false,
    "editor.suggest.snippetsPreventQuickSuggestions": false,
    "editor.tabCompletion": "onlySnippets",
    "editor.wordBasedSuggestions": "off"
}
```

> **重要**：VS Code 需要**完全退出后重新启动**才能读到新的 PATH 和环境变量。

---

## 四、验证用的示例项目

`G:\flutter_projects\hello_flutter`（用 `flutter create --platforms=android,windows,web` 创建）

已产出：
- `build\web\` —— Web 构建成功
- `build\app\outputs\flutter-apk\app-debug.apk` —— Android 调试包构建成功（143.5 MB）

---

## 五、剩下唯一一步：Windows 桌面支持（需要管理员权限）

flutter doctor 报 Visual Studio 缺少两个组件：
- **C++ CMake tools for Windows**（`Microsoft.VisualStudio.Component.VC.CMake.Project`）
- **Windows 11 SDK**（`Microsoft.VisualStudio.Component.Windows11SDK.28000`）

MSVC 编译器本身（v145 / 14.51.36231）已经装好了，只差这两个。
它们只能通过 Visual Studio 安装器以管理员身份安装，而当前会话没有管理员权限（UAC 是过滤令牌）。

**解决方法（二选一，任选其一即可）：**

1. 直接双击 / 右键“以管理员身份运行”桌面上的：
   `enable-flutter-windows-desktop.bat`
   （同一份文件也在 `F:\Android\enable-flutter-windows-desktop.bat`）

2. 或手动执行：
   ```bat
   "C:\Program Files (x86)\Microsoft Visual Studio\Installer\setup.exe" modify ^
     --installPath "C:\Program Files\Microsoft Visual Studio\18\Community" ^
     --add Microsoft.VisualStudio.Component.VC.CMake.Project ^
     --add Microsoft.VisualStudio.Component.Windows11SDK.28000 ^
     --quiet --norestart --wait
   ```

大约需要下载 2 GB，耗时 5～15 分钟。装完后 `flutter run -d windows` 即可用。

> 如果暂时不需要 Windows 桌面应用，可以先跳过 —— 现在 Android + Web 已经完全可用。

---

## 六、网络注意事项（本机重要的坑）

这台机器的网络有以下限制，已经踩到并绕过：

| 域名 | 状态 | 影响 |
|---|---|---|
| `pub.dev` | ✅ 通 | Dart 依赖正常 |
| `dl.google.com` | ✅ 通 | Android SDK、Gradle 的 google() 仓库正常 |
| `repo.maven.apache.org` | ✅ 通 | Gradle 的 mavenCentral() 正常 |
| `storage.googleapis.com` | ✅ 通 | Flutter 引擎产物正常 |
| **`github.com`** | ❌ 不通 | **Gradle 发行版下载会卡死** |
| **`maven.google.com`** | ❌ 不通 | 只是 doctor 的网络检查报警，不影响构建 |

### Gradle 发行版下载会卡死的原因

`services.gradle.org/distributions/*.zip` 会 307 跳转到 `github.com`，
而 github 不通，所以 `flutter build apk` 会永远卡在 0 字节。

**已经处理**：手动从腾讯镜像下载了 Gradle 9.3.1 并放入 wrapper 缓存，
所以用 Flutter 3.47.5 默认版本的构建现在不会再卡。

**以后再遇到**（比如项目用了别的 Gradle 版本）：运行
```powershell
powershell -ExecutionPolicy Bypass -File F:\Android\use-gradle-mirror.ps1 -ProjectDir <项目路径>
```
把项目的 `gradle-wrapper.properties` 指向腾讯镜像即可。

可用的镜像：`mirrors.cloud.tencent.com/gradle`（约 4 MB/s）、`mirrors.huaweicloud.com/gradle`（约 2.7 MB/s）。

---

## 七、快速开始

```powershell
# 新建项目
flutter create my_app
cd my_app

# 运行 / 调试（VS Code 里按 F5 也可以）
flutter run -d chrome      # Web
flutter run -d edge        # Web（Edge）
flutter run -d windows     # Windows 桌面（需先完成第五节）

# Android：插上手机开启 USB 调试，或先只构建
flutter devices
flutter build apk --debug
```

---

## 八、其他记录

- **C 盘空间偏紧**：本次搭建后 C 盘剩余约 9.1 GB（Gradle 缓存占约 3.4 GB，位于
  `C:\Users\Administrator\.gradle`）。Android 开发长期使用建议留意 C 盘空间，
  必要时可以把 `GRADLE_USER_HOME` 迁到大盘（F 盘还有 252 GB）。
- **未安装 Android 模拟器**：模拟器需要管理员权限装驱动 + 开启虚拟化。
  插真机（USB 调试）不需要管理员权限，完全可用。如需要模拟器告诉我。
- 过程中我在桌面触发过一次 UAC 测试弹窗（已确认被取消），当前没有遗留弹窗。
- 已清理临时安装包约 507 MB。
