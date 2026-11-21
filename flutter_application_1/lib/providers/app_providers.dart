/// ─────────────────────────────────────────────────────────
/// 依赖注入的**唯一根节点**
///
/// 【这个文件为什么重要到值得单独一个】
/// 因为「Mock 还是真后端」「用哪个 token」「哪个 repository 是哪个实现」
/// 这三类决定**只在这里出现一次**。别处的代码一律只写 `ref.watch(xxxProvider)`，
/// 没有人 new 具体实现。
///
/// 检验它有没有做到位的方法很简单：**接真后端那天，改动量应当只有这个文件里的
/// 一个 if 分支**。如果那天发现要改页面，说明某个地方绕过 DI 直接 new 了实现。
///
/// 【为什么 Mock 切的是 ApiClient 而不是 Repository】
/// 如果 Mock 掉 Repository，DTO 解析、错误码映射、分页拼装、幂等处理
/// 这些最容易写错的部分就全被绕过去了 —— Mock 阶段一路绿灯，
/// 接真后端当天集中爆雷。现在 FakeApiClient 返回的是**和 §12.1 逐字一致的
/// JSON**，上面几层全部走真实代码路径。
/// ─────────────────────────────────────────────────────────
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/env.dart';
import '../core/network/api_client.dart';
import '../core/network/dio_api_client.dart';
import '../core/storage/token_store.dart';
import '../data/mock/fake_api_client.dart';
import '../data/remote/remote_asset_repository.dart';
import '../data/remote/remote_auth_repository.dart';
import '../data/remote/remote_credit_repository.dart';
import '../data/remote/remote_generation_repository.dart';
import '../data/remote/remote_me_repository.dart';
import '../data/remote/remote_task_repository.dart';
import '../repositories/asset_repository.dart';
import '../repositories/auth_repository.dart';
import '../repositories/credit_repository.dart';
import '../repositories/generation_repository.dart';
import '../repositories/me_repository.dart';
import '../repositories/task_repository.dart';

/// 运行期配置。`main.dart` 会用 `AppConfig.forApp()` 覆盖它；
/// 测试里不覆盖就能拿到「纯 Mock、极简模式」。
///
/// 【为什么这里的默认值是写死的 mockOnly，而不是 `AppConfig.forApp()`】
/// 因为 provider 层**读不到编译期参数**也不该读（那正是 `main.dart` 唯一的
/// 副作用所在）。这里给的默认值只服务于「没被 override」这一种情况，
/// 而那种情况只出现在测试里 —— 于是它取**安全方向**：宁可给假数据，
/// 也不要让某个忘了 override 的测试偷偷去打真后端。
final appConfigProvider = Provider<AppConfig>((ref) => AppConfig.mockOnly);

/// **关掉 Riverpod 3 的自动重试。**数据 provider 一律传 `retry: noAutoRetry`。
///
/// ─────────────────────────────────────────────────────────
/// 【这是个必须显式处理的坑，不是洁癖】
///
/// Riverpod 3 给**每个** provider 加了默认重试：`build()` 抛异常后
/// 自动重试 10 次，间隔 200ms 起指数退避到 6.4s
/// （见 `ProviderContainer.defaultRetry`）。它只放过两类：
/// `Error` 和 `ProviderException`。
///
/// 对「偶发网络抖动」这当然是好事。但在这个项目里它会破坏两件
/// 我们**故意建立**的东西：
///
/// 1. **界面上的「重试」按钮会变成假按钮。** 用户还没点，背后已经试了 10 次；
///    而且错误提示会在半分钟里反复消失又出现，看起来像界面在抽风。
///    这个项目对错误的态度是**显式**的：哪句话、能不能重试、要不要登出，
///    都要被写出来（见 `AppException.isRetryable`），而不是交给一个
///    看不见的退避循环。
///
/// 2. **测试不再确定。** `pumpAndSettle` 会把退避的定时器一路推完，
///    一个「预期失败」的用例实际会发十来次请求 —— 断言通过与否开始取决于
///    时钟推进的方式，而不是代码的行为。
///
/// 关掉之后，失败的 provider 会**稳定地停在错误态**，
/// 由页面上的重试按钮和 `refresh()` 负责重来。
/// ─────────────────────────────────────────────────────────
Duration? noAutoRetry(int retryCount, Object error) => null;

/// Token 的持久化实现。
///
/// 【测试为什么一定要覆盖它】因为默认实现会写进系统密钥库（Android 的
/// EncryptedSharedPreferences / iOS 的 Keychain），单元测试去碰真机密钥库
/// 既污染开发机，并行跑时还会互相踩。测试里换成 [InMemoryTokenStore]。
final tokenStoreProvider = Provider<TokenStore>((ref) => SecureTokenStore());

/// 当前登录 token 的**内存副本**，供 [apiClientProvider] 同步读取。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么 token 存了两份（密钥库 + 这里）】
/// 因为两者的用途不一样，而且**一个都去不掉**：
///
/// * [tokenStoreProvider] 是**异步**的 —— 它要落盘，冷启动时才能恢复登录。
///   但给 HTTP 头加 `Authorization` 是**同步**动作：dio 的拦截器不会等你 await。
/// * 这个 provider 就是那个同步副本：登录后立刻写入，登出后清空，
///   冷启动恢复登录时也会补写一次。
///
/// 【会不会不一致】会，但方向是安全的：唯一的风险是「落盘成功、内存没同步」，
/// 那表现为**这次运行没带上鉴权头**（服务端回 401，用户看到「登录已过期」），
/// 而不是「登出之后还带着旧 token 去请求」。
/// 所以写入顺序固定为：**先落盘，再写内存**（见 AuthController._adopt）。
/// ─────────────────────────────────────────────────────────
final authTokenProvider =
    NotifierProvider<AuthTokenNotifier, String?>(AuthTokenNotifier.new);

/// [authTokenProvider] 的写入端。
///
/// 【为什么用 Notifier 而不是一个可变对象】因为哪天需要「401 时自动跳登录页」，
/// 监听这个 provider 就能做到；一个裸的可变字段没有通知能力。
class AuthTokenNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void setToken(String? token) => state = token;
}

/// 通信层。**整个 App 唯一决定「Mock 还是真后端」的地方。**
final apiClientProvider = Provider<ApiClient>((ref) {
  final cfg = ref.watch(appConfigProvider);

  if (!cfg.useMock) {
    return DioApiClient(
      baseUrl: cfg.baseUrl,
      // 【注意这里是函数不是值】见 DioApiClient.tokenProvider 的注释：
      // 传值会让 client 绑死在某一刻的登录态上。
      tokenProvider: () => ref.read(authTokenProvider),
    );
  }

  return FakeApiClient(latency: cfg.taskStageDuration);
});

// ── 六个 repository ─────────────────────────────────────────
//
// 【为什么全部指向 Remote* 实现，哪怕现在是 Mock 模式】
// 因为 Remote* 拿到的就是 apiClientProvider —— 而它现在给的是 FakeApiClient。
// 也就是说 Mock 模式下跑的**已经是真实代码路径**（解析、映射、幂等全走一遍），
// 只是数据是内存造的。这正是我们要的。
//
// 如果反过来在 Mock 模式下换一套「MockRepository」，那这一层就白建了。

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => RemoteAuthRepository(ref.watch(apiClientProvider)),
);

final meRepositoryProvider = Provider<MeRepository>(
  (ref) => RemoteMeRepository(ref.watch(apiClientProvider)),
);

final creditRepositoryProvider = Provider<CreditRepository>(
  (ref) => RemoteCreditRepository(ref.watch(apiClientProvider)),
);

final taskRepositoryProvider = Provider<TaskRepository>(
  (ref) => RemoteTaskRepository(ref.watch(apiClientProvider)),
);

final generationRepositoryProvider = Provider<GenerationRepository>(
  (ref) => RemoteGenerationRepository(ref.watch(apiClientProvider)),
);

final assetRepositoryProvider = Provider<AssetRepository>(
  (ref) => RemoteAssetRepository(ref.watch(apiClientProvider)),
);
