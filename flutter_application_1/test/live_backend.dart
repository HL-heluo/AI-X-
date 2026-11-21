/// 第二层契约测试的接线件 —— **不是测试，是公共件**（和 `shell_harness.dart` 同类）
///
/// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/// 【这个文件存在，是为了让「换掉 apiClientProvider 就能上后端」这句话
///   从一句承诺变成一条命令】
///
/// 全项目的架构承诺是：**接真后端只需要改 `app_providers.dart` 里
/// `apiClientProvider` 的一个 if 分支**。这句话在 B3–B7 期间无法验证 ——
/// 因为 `DioApiClient` 那个分支后面根本没有东西。
///
/// 现在后端有了，所以这条承诺可以被**执行**了：
///
///     # 默认（Mock，一整轮都在本机内存里跑）
///     flutter test
///
///     # 第二层契约门禁（打真后端）
///     flutter test --concurrency=1 \
///                  --dart-define=USE_MOCK=false \
///                  --dart-define=API_BASE_URL=http://127.0.0.1:8000
///
/// ─────────────────────────────────────────────────────────
/// 【⚠️ `--concurrency=1` 不是「稳妥起见」，是**必须的**】
///
/// `flutter test` 默认**并行跑多个测试文件**（每个文件一个 isolate，
/// 数量跟 CPU 核数走）—— 这在 Mock 下完全没问题（每个容器一套自己的内存）。
/// 但真后端是**一个进程、一个库**，而 `repository_layer_test` 和
/// `live_contract_test` **每个用例前都要清库**。并行的话：
///
///   A 文件刚 drop_all 完 → B 文件正在插数据 → A 的 create_all 撞上
///   「table users already exists」，B 的插入撞上「no such table」。
///
/// 后果不是「偶尔红一下」，而是**一片看起来像业务逻辑坏了的报错**：
/// 401 未登录、409 用户名已被占用、reset 自己 500 —— 而它们跟被测代码
/// 一点关系都没有（后端日志里只有 SQLite 的 drop/create 打架）。
/// 这个坑实测踩过，所以命令写在这里，不要图省事去掉。
/// ─────────────────────────────────────────────────────────
///
/// 【⚠️ 关键：这里**没有**自己造一套配置】
///
/// 用的是 `AppConfig.forTests()`，而它与 `main.dart` 的 `AppConfig.forApp()`
/// **共用同一段装配代码**（`AppConfig._read`），**只差两个默认值**：
/// App 默认连真后端，测试默认 Mock。
///
/// 所以第二层跑的不是「测试专用的接线」，而是**内测包上线时的同一条路**：
/// 命令行 → `AppConfig` → `apiClientProvider` 的 if → `DioApiClient`。
/// 任何一环写错，这一遍就会红。
///
/// 【为什么默认值必须不一样、又必须只差默认值】两个原因各占一半：
///   · **必须不一样** —— 裸跑 `flutter test` 不能去打真后端，见下面那段；
///   · **必须只差默认值** —— 差得再多一点，「测的是测试自己」这条就会回来。
///
/// 如果这里改成手写 `DioApiClient(baseUrl: 'http://...')`，那测的
/// 就只是「DioApiClient 能不能用」，而**「那个 if 分支接得对不对」
/// 仍未被验证过** —— 而那恰恰是唯一没被验证过的东西。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么 Mock 模式下这些用例是 skip 而不是失败】
///
/// 因为它们要一个**活着的后端**，而默认的 `flutter test` 不该依赖
/// 任何外部进程（那会让「本机没起后端」变成一片红）。
/// skip 在输出里是**可见**的（`~17 -N: skipped`），不会被当成通过。
/// **这也是 `AppConfig.forTests()` 的默认值仍然是 Mock 的全部理由** ——
/// 2026-10-17 把 App 的默认翻成真后端时，测试这一侧特意没跟着翻。
///
/// 【反过来：一旦显式指名要打真后端，连不上就必须失败】
/// 所以这里是「按命令行分叉」，不是「按能不能连上分叉」。
/// 如果写成「连不上就 skip」，那某天后端挂了、测试会静悄悄地全绿 ——
/// 一个会自己消失的门禁比没有门禁更危险。
/// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/core/env.dart';
import 'package:flutter_application_1/core/storage/token_store.dart';
import 'package:flutter_application_1/providers/app_providers.dart';
import 'package:flutter_application_1/providers/auth_providers.dart';

/// 本次运行用的配置 —— **和 `main.dart` 取配置走同一段装配代码**。
///
/// 【为什么是顶层 final 而不是函数】Dart 的顶层 final 是**惰性**求值的，
/// 第一次被读到才计算。所以「`USE_MOCK=false` 却没给 `API_BASE_URL`」
/// 这个错误会在第一条用例里以 `AppConfig` 那句看得懂的 `StateError` 出现，
/// 而不是在 import 阶段炸成一片看不懂的堆栈。
///
/// 【为什么用 `forTests` 而不是 `forApp`】2026-10-17 起两者的默认值不同：
/// App 默认连真后端，**测试默认 Mock**。这里要的是后者 —— 裸跑
/// `flutter test` 不能去打真后端（那 24 条 live 用例靠默认值 skip）。
/// 要真后端仍然是显式那句 `--dart-define=USE_MOCK=false`，命令行一个字没变。
final AppConfig runConfig = AppConfig.forTests();

/// 本次运行打的是不是一个真的后端。
bool get isLiveBackend => !runConfig.useMock;

/// 造一个测试用的容器 —— **Mock 和真后端共用这一个入口**。
///
/// ─────────────────────────────────────────────────────────
/// 【两个 override，以及为什么只该有这两个】
///
/// 1. **`appConfigProvider`**：默认值是 `AppConfig.mockOnly`（写死的 Mock）。
///    把它换成本次运行的配置，就是这个文件存在的**全部理由** ——
///    换掉之后 `apiClientProvider` 里那个 if 自然走到 `DioApiClient` 那一支，
///    于是「接真后端只改一个 if」这句承诺被真的执行了一遍。
///
/// 2. **`tokenStoreProvider`**：默认实现 `SecureTokenStore` 会去写**系统密钥库**
///    （Android 的 EncryptedSharedPreferences / 浏览器 WebCrypto）。
///    测试不该碰真机密钥库：既污染开发机，并行跑时还会互相踩。
///    这条在 Mock 模式下也必须有（见 `app_providers.dart` 里那段注释）。
///
/// 【为什么这里就不该再多 override 别的】
/// 多一个 override 就多绕过一层真实代码。第二层要验的正是
/// 「上面那几层能不能接住真后端的响应」—— 把 repository 也覆盖掉，
/// 这个文件就变成了在测自己。
///
/// 【为什么是「造容器」而不是「返回 override 列表」】
/// 因为 `Override` 这个类型**没有被 riverpod 的公共 API 导出**
/// （它是 `src/core/override.dart` 里的 sealed class，只是漏在
/// `ProviderContainer.test` 的签名里）。写不出 `List<Override>` 这个类型，
/// 所以只能在这儿把容器造出来。这不是风格选择。
/// ─────────────────────────────────────────────────────────
ProviderContainer testContainer() => ProviderContainer.test(
      overrides: [
        appConfigProvider.overrideWithValue(runConfig),
        tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
      ],
    );

/// 注册一个用户，**并把登录态装成线上那个样子**，返回容器。
///
/// ─────────────────────────────────────────────────────────
/// 【⚠️ 为什么必须走 `authControllerProvider`，不能直接调 repository】
///
/// 这是 B2b 第一次跑第二层门禁时撞出来的，而且撞得很典型：
/// 直接 `authRepositoryProvider.register(...)` 拿到 session 之后，
/// 容器里**没有任何人把 token 装进 `authTokenProvider`** ——
/// 于是后续每个请求都是**裸奔**的，真后端一律回 401。
///
/// 【为什么 Mock 模式下这个错永远暴露不出来】
/// 因为 `FakeApiClient` 是内存假服务端，它有自己的一套登录状态，
/// **根本不看 `Authorization` 头**。所以在 Mock 下「忘记带 token」
/// 和「带对了」完全一样。
///
/// 而线上是两条路：token 先落盘（`TokenStore`）、再写进内存副本
/// （`authTokenProvider`，dio 的拦截器同步读它），顺序都不能反。
/// 这件事由 `AuthController._adopt` 负责 —— 也就是登录页按下
/// 「注册」时走的那条路。
///
/// 所以夹具要做的就是**走那条路**，而不是在这里把它抄一遍：
/// 抄一遍的话，`_adopt` 将来多一句（比如写个时间戳）夹具就悄悄过时了，
/// 而门禁会继续绿。用真正的 controller，就没这个可能。
/// ─────────────────────────────────────────────────────────
Future<ProviderContainer> registeredContainer({String username = 'alice'}) async {
  final c = testContainer();
  await c.read(authControllerProvider.notifier).register(
        inviteCode: 'MOCK',
        username: username,
        password: 'pw123456',
      );
  return c;
}

/// 把后端清回空库，并**确认它真的清干净了**。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么每条用例前都要重置】
///
/// 因为真后端是**跨用例共享的状态**（这一点和 Mock 根本不同：Mock 每个容器
/// 一个实例，互不相干）。不重置的话：
///
///   · 第二条用例注册 `alice` 会撞上第一条留下的 `alice` → 409；
///   · 「注册赠送 50」的断言会因为余额被上一条用例花掉而失败；
///   · 而**失败原因和被测代码毫无关系**，排查时最浪费时间。
///
/// 【为什么要断言 `invite_code == "MOCK"`】
/// 因为整套测试都用 `MOCK` 注册（`repository_layer_test` / `auth_flow_test` /
/// 浏览器剧本都是它）。reset 只清库、不种邀请码的话，第一条用例会以
/// 「邀请码无效」红掉 —— 那看起来像**业务错误**，实际是测试夹具坏了。
/// 断在夹具里，比让它伪装成业务失败强。
/// ─────────────────────────────────────────────────────────
Future<void> resetLiveBackend() async {
  final dio = Dio(
    BaseOptions(
      baseUrl: runConfig.baseUrl,
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 20),
      validateStatus: (_) => true,
    ),
  );

  final Response<dynamic> res;
  try {
    res = await dio.post<dynamic>('/__test/reset');
  } on DioException catch (e) {
    fail(
      '连不上后端 ${runConfig.baseUrl}：${e.message}\n'
      '第二层契约测试要一个**活着的**后端。起它的命令：\n'
      '  cd /g/AIVideo/backend\n'
      '  TEST_MODE=1 PYTHONIOENCODING=utf-8 '
      '.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000\n'
      '（TEST_MODE=1 不能少 —— 关着时 /__test/* 在路由表里根本不存在。）',
    );
  }

  if (res.statusCode == 404) {
    fail(
      '后端在 ${runConfig.baseUrl}，但 /__test/reset 不存在 —— TEST_MODE 没开。\n'
      '它是**硬门禁**（关着时这些路由根本不注册），所以这是配置问题，不是后端 bug。\n'
      '按上面那条命令加上 TEST_MODE=1 重启。',
    );
  }

  final body = res.data;
  if (res.statusCode != 200 || body is! Map || body['invite_code'] != 'MOCK') {
    fail('reset 没成功（HTTP ${res.statusCode}）：$body');
  }
}

/// 一条**裸**的 dio 请求，用来断言「响应体在网络上到底长什么样」。
///
/// 【为什么不能只用 `apiClientProvider` 那条路】
/// 因为 `DioApiClient._decode` 会把响应体转成 `Map` 再交出来。经过那一层之后，
/// 「服务端到底发的是 `{...}` 还是 `[ {...} ]`」就看不出来了，而这正是
/// `_decode` 唯一做错就会全盘皆输的地方。
///
/// 用裸 dio 还能拿到**状态码**（405 / 404 这类），
/// 以及那几条不该由 `AppException` 表达的东西（比如「这条路径存不存在」）。
Future<Response<dynamic>> rawRequest(
  String path, {
  String method = 'GET',
  Object? body,
  String? token,
}) {
  final dio = Dio(
    BaseOptions(
      baseUrl: runConfig.baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
      validateStatus: (_) => true,
      headers: <String, dynamic>{
        if (token != null) 'Authorization': 'Bearer $token',
      },
    ),
  );
  return dio.request<dynamic>(path, data: body, options: Options(method: method));
}

/// 给某个用户加积分 —— 走 `/__test/grant`（§15.1 的那个「管理员脚本」）。
///
/// 【为什么测试需要它】有一条用例要验「打满每日配额」（默认 20 条/天），
/// 而注册送的 50 积分只够 12 条图（4 积分/张）—— 不补钱的话，
/// 第 13 条会先撞上「积分不足」，**根本走不到配额那道闸**，
/// 于是那条用例测的东西和它声称要测的不是一回事。
Future<void> grantCredits(
  String username, {
  int amount = 500,
}) async {
  final res = await rawRequest(
    '/__test/grant',
    method: 'POST',
    body: <String, dynamic>{'username': username, 'amount': amount},
  );
  if (res.statusCode != 200) {
    fail('发积分失败（HTTP ${res.statusCode}）：${res.data}');
  }
}
