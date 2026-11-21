import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/app.dart';
import 'package:flutter_application_1/app_shell.dart';
import 'package:flutter_application_1/core/constants/api_paths.dart';
import 'package:flutter_application_1/core/constants/error_codes.dart';
import 'package:flutter_application_1/core/env.dart';
import 'package:flutter_application_1/core/network/api_client.dart';
import 'package:flutter_application_1/core/network/api_exception.dart';
import 'package:flutter_application_1/core/storage/token_store.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/pages/auth/login_page.dart';
import 'package:flutter_application_1/pages/splash/splash_page.dart';
import 'package:flutter_application_1/providers/app_providers.dart';
import 'package:flutter_application_1/providers/auth_providers.dart';

import 'shell_harness.dart';
/// ─────────────────────────────────────────────────────────
/// B4 的验收测试：登录态分发 + 登录页
///
/// 【为什么这一批必须有自己的测试】
/// 因为 B4 引入了一个**全局的、带分支的启动逻辑**：
/// 冷启动要先读 token、验证 token，再决定给用户看登录页还是主界面。
/// 这条路径的每一个分支都很难手工试全 ——
/// 「token 过期时会怎样」这种事，手工测需要等 JWT 真的过期。
///
/// 【测试的接缝在哪】
/// 两处 override，正好就是 B4 新增的两个接缝：
/// * [tokenStoreProvider] → 内存实现，不碰系统密钥库
/// * [apiClientProvider]  → 共用的 FakeApiClient，让「重启 App」能复用同一份
///   「服务端数据」
/// ─────────────────────────────────────────────────────────

/// 起一个 App，返回它的容器。
///
/// [fake] 和 [store] 都可以跨容器复用 —— 这正是「关掉 App 再打开」的模拟方式：
/// 容器（= 一次进程）换新的，假服务端和密钥库（= 真实世界里的外部状态）留着。
Future<ProviderContainer> _pumpApp(
  WidgetTester tester, {
  /// 类型放宽到 [ApiClient]（而不是 FakeApiClient）：有的用例要在接缝上
  /// 装一个「只说某一种错」的装饰器，它不再是 Mock 本身。
  required ApiClient fake,
  required TokenStore store,
}) async {
  final container = ProviderContainer.test(
    overrides: [
      appConfigProvider.overrideWithValue(AppConfig.mockOnly),
      apiClientProvider.overrideWithValue(fake),
      tokenStoreProvider.overrideWithValue(store),
    ],
  );

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const AiVideoApp(),
    ),
  );
  // 【为什么要 settle】冷启动要先 await 一次读 token（是异步的），
  // 不 settle 的话测到的永远是 Splash 那一帧。
  await tester.pumpAndSettle();
  return container;
}

/// 读 token 会慢一拍的 store。
///
/// 【为什么需要它】`InMemoryTokenStore.read()` 实际上是零耗时的
/// （一个 await 就返回了），所以「启动页」那一帧在测试里根本抓不到 ——
/// 但真实设备上 `SecureTokenStore` 要过一次平台通道，是**有真实耗时**的，
/// 那一帧真的会被画出来。
///
/// 要断言「启动时先画启动页」这件事，就必须让这个耗时在测试里真实存在。
class _SlowTokenStore implements TokenStore {
  @override
  Future<String?> read() async {
    await Future<void>.delayed(const Duration(milliseconds: 50));
    return null;
  }

  @override
  Future<void> write(String token) async {}

  @override
  Future<void> clear() async {}
}

/// 一个「邀请码不对」的假服务端：注册接口一律拒，其余原样转发给真 Mock。
///
/// 【为什么必须在 ApiClient 这一层装，而不是给 FakeApiClient 加条规则】
/// 因为 Mock 是**故意**放行任何非空邀请码的 —— 演示模式里让人猜一串
/// 服务端才有的白名单码毫无意义（见 `fake_api_client.dart` 注册那一段）。
/// 邀请码白名单只有真后端才有，所以只能在接缝上把它模拟出来。
///
/// 【为什么抛的是 `fromResponse` 而不是手写一个 AppException】
/// 因为要走的正是**真后端那天要走的那条路**：字符串码 → `tryFromWire` → 枚举。
/// 手写 `AppException(code: ...)` 会把「认不认得出这个码」这一步跳过去，
/// 而这一步恰恰是这个用例要守的东西。
class _InviteRejectingClient implements ApiClient {
  final FakeApiClient _inner = FakeApiClient();

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body}) {
    if (path == ApiPaths.register) {
      throw AppException.fromResponse(
        httpStatus: ApiErrorCode.inviteInvalid.httpStatus,
        codeWire: ApiErrorCode.inviteInvalid.wire,
        message: 'invite code not found', // 后端给开发看的那句，不该上屏
      );
    }
    return _inner.post(path, body: body);
  }

  @override
  Future<Map<String, dynamic>> get(String path, {Map<String, dynamic>? query}) =>
      _inner.get(path, query: query);

  @override
  Future<Map<String, dynamic>> delete(String path) => _inner.delete(path);

  @override
  Future<Map<String, dynamic>> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    String? mimeType,
  }) =>
      _inner.upload(path, bytes: bytes, filename: filename, mimeType: mimeType);
}

/// 填表并提交。注册模式下多填一个邀请码。
Future<void> _submitForm(
  WidgetTester tester, {
  required String username,
  required String password,
  String inviteCode = '',
}) async {
  if (inviteCode.isNotEmpty) {
    await tester.enterText(
      find.byKey(const Key('login.inviteCode')),
      inviteCode,
    );
  }
  await tester.enterText(find.byKey(const Key('login.username')), username);
  await tester.enterText(find.byKey(const Key('login.password')), password);
  await tester.tap(find.byKey(const Key('login.submit')));
  await tester.pumpAndSettle();
}

void main() {
  group('冷启动分发', () {
    testWidgets('没有任何 token → 落在登录页', (tester) async {
      await _pumpApp(tester, fake: FakeApiClient(), store: InMemoryTokenStore());

      expect(find.byType(LoginPage), findsOneWidget);
      expect(find.byType(AppShell), findsNothing);
    });

    testWidgets('启动时先显示过渡页，不是直接闪出登录页', (tester) async {
      final container = ProviderContainer.test(
        overrides: [
          appConfigProvider.overrideWithValue(AppConfig.mockOnly),
          apiClientProvider.overrideWithValue(FakeApiClient()),
          tokenStoreProvider.overrideWithValue(_SlowTokenStore()),
        ],
      );

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const AiVideoApp(),
        ),
      );

      // 【只 pump 一帧，不等异步完成】这一帧就是「还不知道登没登录」。
      // 如果这时画的是登录页，用户会看到它闪一下再被换掉 ——
      // 而且如果他手快已经在输密码了，输入框会被整页换掉。
      await tester.pump();
      expect(find.byType(SplashPage), findsOneWidget);
      expect(find.byType(LoginPage), findsNothing);

      // 读 token 完成后才落到真正该去的地方
      await tester.pumpAndSettle();
      expect(find.byType(LoginPage), findsOneWidget);
      expect(find.byType(SplashPage), findsNothing);
    });

    testWidgets('token 已失效 → 清掉它并回到登录页，不卡在启动页', (tester) async {
      // 一个假服务端不认识的 token，等价于「JWT 过期了」
      final store = InMemoryTokenStore('早就过期的token');

      await _pumpApp(tester, fake: FakeApiClient(), store: store);

      expect(find.byType(LoginPage), findsOneWidget);
      // 【别让坏 token 留在盘上】否则每次启动都要拿它去撞一次墙，
      // 而且用户在登录页上会一直看到「登录已过期」的残留状态。
      expect(await store.read(), isNull);
    });

    testWidgets('token 有效 → 直接进主界面，不用重新登录', (tester) async {
      final fake = FakeApiClient();
      final store = InMemoryTokenStore();

      // 第一次运行：注册（这一步会把 token 写进 store）
      final first = await _pumpApp(tester, fake: fake, store: store);
      await first.read(authControllerProvider.notifier).register(
            inviteCode: 'MOCK',
            username: 'alice',
            password: 'pw123456',
          );
      expect(await store.read(), isNotNull);

      // 第二次运行：新容器、同一份假服务端和同一个密钥库
      await _pumpApp(tester, fake: fake, store: store);
      expect(find.byType(AppShell), findsOneWidget);
      expect(find.byType(LoginPage), findsNothing);

      // 【为什么要收尾】这一条把主界面真的挂起来了，而首页会 watch
      // 一个 autoDispose 的 provider（生成按钮下的报价）。
      // 不收尾的话测试会以「A Timer is still pending」失败 ——
      // 完整原因见 `unmountAndDrain` 的注释。
      await unmountAndDrain(tester);
    });
  });

  group('注册', () {
    testWidgets('填齐信息 → 进主界面', (tester) async {
      await _pumpApp(tester, fake: FakeApiClient(), store: InMemoryTokenStore());

      await tester.tap(find.byKey(const Key('login.tab.register')));
      await tester.pumpAndSettle();

      // 注册模式才有邀请码输入框
      expect(find.byKey(const Key('login.inviteCode')), findsOneWidget);

      await _submitForm(
        tester,
        username: 'alice',
        password: 'pw123456',
        inviteCode: 'MOCK',
      );

      expect(find.byType(AppShell), findsOneWidget);

      // 主界面在树里 → 收尾，理由见 `unmountAndDrain`
      await unmountAndDrain(tester);
    });

    testWidgets('用户名被占用 → 说「已被占用」，不说「稍后重试」', (tester) async {
      // 【为什么要建两份 store】因为 store 代表「这台设备」。
      // 复用同一个 store 的话，第二台设备会直接继承第一台的登录态 ——
      // 那就测不到「另一个人来注册同名账号」这个场景了。
      // 而 fake（= 服务端）必须共用，否则第二个用户面对的是一个空数据库，
      // 名字根本没被占用。
      final fake = FakeApiClient();

      // 先占掉这个名字
      final first = await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await first.read(authControllerProvider.notifier).register(
            inviteCode: 'MOCK',
            username: 'alice',
            password: 'pw123456',
          );

      // 换一台干净的设备，用同样的名字注册
      await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await tester.tap(find.byKey(const Key('login.tab.register')));
      await tester.pumpAndSettle();
      await _submitForm(
        tester,
        username: 'alice',
        password: 'other123',
        inviteCode: 'MOCK',
      );

      // 【这条断言守的是「文案不能撒谎」】
      // 服务端返回的 409 在 §12.3 里没有对应的业务错误码，
      // 所以 AppException.userMessage 会退化成「出错了，请稍后重试」——
      // 用户会一直重试，永远试不出结果。登录页必须自己把话说明白。
      expect(find.textContaining('已经被占用'), findsOneWidget);
      expect(find.textContaining('稍后重试'), findsNothing);
      expect(find.byType(LoginPage), findsOneWidget);
    });

    testWidgets('邀请码无效 → 说「邀请码无效」，不说「连不上服务器」', (tester) async {
      await _pumpApp(
        tester,
        fake: _InviteRejectingClient(),
        store: InMemoryTokenStore(),
      );

      await tester.tap(find.byKey(const Key('login.tab.register')));
      await tester.pumpAndSettle();
      await _submitForm(
        tester,
        username: 'alice',
        password: 'pw123456',
        inviteCode: 'WRONG-CODE',
      );

      // 【这条断言守的是同一类谎话的另一半】
      // `INVITE_INVALID` 是后端才会发的码，而 §12.3 的表里本来没有它 ——
      // 认不出来的码在 `AppException` 里退化成 `code == null`，
      // 于是这一页会说出那句通用的「连不上服务器，检查一下网络再试」。
      //
      // 那是在**撒谎**：网络好得很，错的是手里那个邀请码。
      // 用户会去关 Wi-Fi 重连、换 4G、找客服说「你们服务器坏了」——
      // 而该改的地方就在他眼前。这和 B7′ 修掉的「请先充值」是同一类：
      // 把用户支去解决一个不存在的问题。
      expect(find.textContaining('邀请码无效'), findsOneWidget);
      expect(find.textContaining('连不上服务器'), findsNothing);
      // 后端给开发看的那句原文（`message`）绝不能上屏
      expect(find.textContaining('invite code not found'), findsNothing);
      expect(find.byType(LoginPage), findsOneWidget);
    });
  });

  group('登录', () {
    testWidgets('注册表单建的号，登录表单能登进去（一来一回）', (tester) async {
      // 【为什么这一条是 B7 才补上的】因为上面那些用例里，「注册」和
      // 「登录」是**两个各自成立的半边**：
      //   · 注册走的是 `authController.register(...)`（控制器 API）；
      //   · 登录走的是登录页的表单。
      // 也就是说「注册表单里填的那个密码，登录时能不能用」从来没人测过 ——
      // 而这一条正是**真的走一遍界面**才发现的：B7 在浏览器里用注册表单
      // 建了个号，登出之后用同一个用户名密码登录，被挡在门外。
      // （后来查明那次是自动化打字的锅，见 HANDOFF §9；
      //   但「没人测过」这件事是真的，所以这条留在测试里。）
      final fake = FakeApiClient();

      // 1. 用**注册表单**建号（不是控制器 API —— 那正是上一句说的差别）
      await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await tester.tap(find.byKey(const Key('login.tab.register')));
      await tester.pumpAndSettle();
      await _submitForm(
        tester,
        username: 'alice',
        password: 'pw123456',
        inviteCode: 'MOCK',
      );
      expect(find.byType(AppShell), findsOneWidget);

      // 2. 换一台干净设备（= 登出后重开），用**登录表单**进去
      await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await _submitForm(tester, username: 'alice', password: 'pw123456');

      // 【这条断言就是「密码没被注册那一步改过」】
      // 中间任何一个环节（本地校验、控制器、请求体拼装）动了密码，
      // 用户都会在「我明明刚注册过」的地方被挡住 —— 而这是最难自查的
      // 一类 bug：他看到的两个框里都是对的。
      expect(find.byType(AppShell), findsOneWidget);
      expect(find.textContaining('用户名或密码不正确'), findsNothing);

      await unmountAndDrain(tester);
    });

    testWidgets('密码打错 → 说「用户名或密码不正确」，不说「登录已过期」', (tester) async {
      final fake = FakeApiClient();

      final first = await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await first.read(authControllerProvider.notifier).register(
            inviteCode: 'MOCK',
            username: 'alice',
            password: 'pw123456',
          );

      // 换一台干净设备，用错密码登录。
      // 【密码要够 6 位】否则会被本地校验先挡下来（「密码至少 6 位」），
      // 那次请求压根不会发出去 —— 也就测不到服务端 401 的文案了。
      await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await _submitForm(tester, username: 'alice', password: 'wrongpass');

      // 【这条断言是 B4 里最容易被写错的一处】
      // 密码错时服务端返回 401，而 AppException 对 401 的默认说法是
      // 「登录已过期，请重新登录」—— 用户刚打开 App，压根没登录过。
      expect(find.textContaining('用户名或密码不正确'), findsOneWidget);
      expect(find.textContaining('登录已过期'), findsNothing);
      expect(find.byType(LoginPage), findsOneWidget);
    });

    testWidgets('登录成功后按返回键不会退回登录页', (tester) async {
      final fake = FakeApiClient();

      final first = await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await first.read(authControllerProvider.notifier).register(
            inviteCode: 'MOCK',
            username: 'alice',
            password: 'pw123456',
          );

      await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());
      await _submitForm(tester, username: 'alice', password: 'pw123456');
      expect(find.byType(AppShell), findsOneWidget);

      // 【为什么这条值得测】因为登录页和主界面是同一层里的两个分支，
      // 不是路由栈的两页。如果有人图省事改成 Navigator.push，
      // 这里就会退回到一个「已经无主的登录页」，而且用户按返回
      // 能退出登录态 —— 那是很严重的问题。
      final navigator = tester.state<NavigatorState>(find.byType(Navigator));
      expect(navigator.canPop(), isFalse);

      // 主界面在树里 → 收尾，理由见 `unmountAndDrain`
      await unmountAndDrain(tester);
    });

    testWidgets('本地校验挡住空字段，不发请求', (tester) async {
      final fake = FakeApiClient();
      await _pumpApp(tester, fake: fake, store: InMemoryTokenStore());

      await tester.tap(find.byKey(const Key('login.submit')));
      await tester.pumpAndSettle();

      expect(find.text('请填写用户名'), findsOneWidget);
    });
  });

  group('登出', () {
    testWidgets('登出 → 回登录页，且 token 被清掉', (tester) async {
      final store = InMemoryTokenStore();
      final container =
          await _pumpApp(tester, fake: FakeApiClient(), store: store);

      await container.read(authControllerProvider.notifier).register(
            inviteCode: 'MOCK',
            username: 'alice',
            password: 'pw123456',
          );
      await tester.pumpAndSettle();
      expect(find.byType(AppShell), findsOneWidget);

      await container.read(authControllerProvider.notifier).logout();
      await tester.pumpAndSettle();

      expect(find.byType(LoginPage), findsOneWidget);
      expect(await store.read(), isNull);
      // 内存里的 token 也要清 —— 否则这次运行还会带着旧 token 发请求
      expect(container.read(authTokenProvider), isNull);
    });
  });

  group('AuthController 的纪律', () {
    test('登录失败不把全局状态弄成错误态', () async {
      final container = ProviderContainer.test(
        overrides: [
          appConfigProvider.overrideWithValue(AppConfig.mockOnly),
          apiClientProvider.overrideWithValue(FakeApiClient()),
          tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
        ],
      );

      // 等 build() 跑完
      await container.read(authControllerProvider.future);
      expect(container.read(authControllerProvider).value, isA<Unauthenticated>());

      await expectLater(
        container
            .read(authControllerProvider.notifier)
            .login(username: 'nobody', password: 'whatever'),
        throwsA(isA<Object>()),
      );

      // 【这条断言守的是一个很具体的界面 bug】
      // 如果登录失败把 state 置成 AsyncError，app.dart 会把它当成
      // 「启动失败」—— 用户会看到一个写着异常的页面，而不是
      // 「用户名或密码不正确」贴在输入框下面。
      final state = container.read(authControllerProvider);
      expect(state.hasError, isFalse);
      expect(state.value, isA<Unauthenticated>());
    });
  });
}
