/// 运行期配置
///
/// 【为什么要有这么一个东西】
/// 因为「Mock 还是真后端」这件事**必须在一次运行内定死**，而且要从命令行能改，
/// 不能靠改代码。内测包、演示包、联调包三种构建，源码应该是同一份。
///
/// 用法：
/// ```
/// flutter run                                        # 默认真后端（本机 8000）
/// flutter run --dart-define=USE_MOCK=true            # 走 Mock，离线改 UI 用
/// flutter run --dart-define=API_BASE_URL=https://api.example.com   # 换后端
/// flutter run --dart-define=MOCK_LATENCY_MS=4000     # Mock 走真实状态机
/// ```
///
/// ─────────────────────────────────────────────────────────
/// 【默认值是「真后端」—— 2026-10-17 从「Mock」翻过来的】
///
/// 原来默认 Mock，理由写在当时那段注释里：「因为本轮后端还不存在」。
/// 后端 B0–B7.4 做完、而且图生视频真网关跑通之后，这个理由没有了，
/// 代价却显出来了：**裸跑任何东西得到的都是全假数据的界面，
/// 而它看起来和真的完全一样**。「界面全对、数据全假」是这一路上
/// 最难当场发现的一类错误 —— 这一轮里就真的被它咬过。
///
/// 翻过来之后，忘带参数得到的是**连不上**（一条看得懂的网络错），
/// 而不是**看起来对**。要假数据得明确说出来：`--dart-define=USE_MOCK=true`。
///
/// ⚠️ **测试跑起来仍然默认 Mock，而且必须仍然默认 Mock** ——
/// 见 [AppConfig.forTests] 那段。`USE_MOCK` 这一个开关同时兼着两件事：
/// 「这个包里连的是谁」和「这次 `flutter test` 是不是在打真后端」。
/// 后一个用途撑着 24 条 live 用例的 skip。
///
/// 【为什么用 --dart-define 而不是配置文件】
/// 因为它是**编译期**注入的：值会被内联进产物，不会在运行时被改。
/// 如果放成配置文件或环境变量，就存在「线上包里被人改成 useMock=true」的可能 ——
/// 那意味着用户看到的全是假数据。
///
/// 【⚠️ 编译期这三个字有个副作用】改完 `--dart-define` **必须重启进程**，
/// 热重载和热重启都不作数（值已经内联进产物了）。改完没停过进程、
/// 然后说「配了没用」，是这里最常见的误判。
/// ─────────────────────────────────────────────────────────
class AppConfig {
  const AppConfig({
    required this.baseUrl,
    this.useMock = true,
    this.taskStageDuration,
  });

  /// 后端地址。走 Mock 时用不上，所以允许为空。
  final String baseUrl;

  /// 是否使用本地 Mock 数据层。
  ///
  /// 【这个字段只存结果，默认值看用途】App 跑起来默认 **false**（真后端），
  /// 测试跑起来默认 **true**（Mock）。两个默认分别在 [AppConfig.forApp]
  /// 与 [AppConfig.forTests] 里，**别在这个字段上找**。
  ///
  /// （这里的 `= true` 只是给「直接 `AppConfig(...)` 构造」用的缺省，
  /// 它是**安全方向**：手写构造时忘了传，得到的是假数据而不是真请求。
  /// 三个正经入口 —— 两个工厂和 [AppConfig.mockOnly] —— 都会显式传值。）
  final bool useMock;

  /// Mock 里一个任务在**每个阶段**停留多久。
  ///
  /// null（默认）表示「极简模式」：任务提交后**立刻成功**，
  /// 不经过 `queued` / `submitted`。
  ///
  /// 设成非 null（比如 4 秒）后，Mock 会真的走状态机：
  /// `queued` →（4 秒）→ `submitted` →（再 4 秒）→ `succeeded`。
  ///
  /// 【为什么值得留这个开关】
  /// 极简模式下，文档里这几件事**根本无法验收**：
  /// 排队位次、轮询退避、「关掉 App 再打开进行中任务还在」、完成通知。
  /// 它们全部依赖「任务会花一段时间」。开这个开关就能手动跑一遍，
  /// 不必等真后端。
  final Duration? taskStageDuration;

  /// 本机后端的地址 —— 那个「不用问也知道」的答案。
  ///
  /// 【为什么 App 可以有这么一个默认值、而测试没有】因为开发机上后端就起在
  /// 这里，这是绝大多数运行场景的唯一答案；而测试跑在哪儿是不确定的，
  /// 给它一个默认值只会把「忘了给地址」变成「静默连了个别的东西」。
  static const String _localBaseUrl = 'http://127.0.0.1:8000';

  /// **App 运行时的配置：默认连真后端。** `main.dart` 只用这一个。
  factory AppConfig.forApp() => _read(
        useMock: const bool.fromEnvironment('USE_MOCK', defaultValue: false),
        baseUrl: const String.fromEnvironment(
          'API_BASE_URL',
          defaultValue: _localBaseUrl,
        ),
        latencyMs: const int.fromEnvironment('MOCK_LATENCY_MS'),
      );

  /// **测试运行时的配置：默认 Mock。**
  ///
  /// 与 [forApp] 只差**两个默认值**，装配代码是同一份（[_read]）——
  /// 这一点是刻意的：`test/live_backend.dart` 存在的全部意义就是
  /// 「走 `main.dart` 走过的那条配置路径」，所以两个入口必须共用同一段装配，
  /// 否则「测的是测试自己」。
  ///
  /// 【为什么测试的默认必须反过来（必须仍然是 Mock）】
  /// 裸跑 `flutter test` 不该去打真后端：那 24 条 live 用例正是靠
  /// `USE_MOCK` 的默认值 skip 掉的，而 skip 是**看得见的**
  /// （静默通过比没有门禁更危险）。默认翻成真后端的话，
  /// 裸跑 `flutter test` 会去连一个可能根本没起来的服务，
  /// 而那 24 条会以一片「连不上」的形式出现 —— 看起来像业务错误。
  ///
  /// 【为什么这里**不给** baseUrl 默认值】
  /// 于是「`USE_MOCK=false` 却忘了给 `API_BASE_URL`」仍然会当场 `StateError`
  /// （见 [_read] 里那个快速失败）。App 那边给默认值，是因为开发机上
  /// 它的答案唯一；测试没有唯一天然答案，就别猜。
  factory AppConfig.forTests() => _read(
        useMock: const bool.fromEnvironment('USE_MOCK', defaultValue: true),
        baseUrl: const String.fromEnvironment('API_BASE_URL'),
        latencyMs: const int.fromEnvironment('MOCK_LATENCY_MS'),
      );

  /// 两个工厂共用的装配 —— **全项目唯一那处「从编译期参数读配置」的地方**。
  ///
  /// 【为什么读那三行不写进这个函数】因为 `fromEnvironment` 的
  /// `defaultValue` 必须是**编译期常量**，形参不满足，所以只能一个工厂一份
  /// （那也正是两个默认值能被分开的原因）。
  static AppConfig _read({
    required bool useMock,
    required String baseUrl,
    required int latencyMs,
  }) {
    // 【快速失败】要用真后端却没给地址，在这里就炸掉，
    // 而不是等用户点了「生成」才收到一个看不懂的网络错误。
    // 启动时崩溃是个难看的 bug，但比线上静默走错分支好得多。
    if (!useMock && baseUrl.isEmpty) {
      throw StateError(
        'USE_MOCK=false 时必须同时提供 API_BASE_URL。\n'
        '示例：flutter run --dart-define=USE_MOCK=false '
        '--dart-define=API_BASE_URL=https://api.example.com',
      );
    }

    return AppConfig(
      baseUrl: baseUrl,
      useMock: useMock,
      taskStageDuration:
          latencyMs > 0 ? Duration(milliseconds: latencyMs) : null,
    );
  }

  /// 测试用：纯 Mock、极简模式。
  ///
  /// 【为什么它不走工厂】Mock 的 widget 测试要的是一个**确定**的环境，
  /// 和命令行上给了什么参数无关 —— 于是它们全部直接 override 成这一个常量。
  /// 副作用是好的：**测试的默认值怎么改都影响不到这些用例**。
  static const AppConfig mockOnly = AppConfig(baseUrl: '');

  @override
  String toString() => 'AppConfig(useMock: $useMock, baseUrl: "$baseUrl", '
      'taskStageDuration: $taskStageDuration)';
}
