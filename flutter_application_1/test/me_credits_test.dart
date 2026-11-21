import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/app.dart';
import 'package:flutter_application_1/app_shell.dart';
import 'package:flutter_application_1/core/env.dart';
import 'package:flutter_application_1/core/network/api_client.dart';
import 'package:flutter_application_1/core/network/api_exception.dart';
import 'package:flutter_application_1/core/storage/token_store.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/pages/auth/login_page.dart';
import 'package:flutter_application_1/pages/credits/credits_page.dart';
import 'package:flutter_application_1/pages/me/settings_page.dart';
import 'package:flutter_application_1/providers/app_providers.dart';
import 'package:flutter_application_1/providers/auth_providers.dart';
import 'package:flutter_application_1/providers/credit_providers.dart';
import 'package:flutter_application_1/providers/me_providers.dart';
import 'package:flutter_application_1/widgets/glass_tab_bar.dart';

/// ─────────────────────────────────────────────────────────
/// B5（前半）的验收测试：「我的」+ 积分
///
/// 【为什么这两屏要合起来测】
/// 因为它们共用同一次 `GET /me`：积分页顶部的余额不是自己拉的，
/// 是从 `meProfileProvider` 里读的。分开测就测不到「点进去之后
/// 余额和上一屏是同一个数」这件事 —— 而那正是拆成两屏之后唯一的风险。
///
/// 【这一批真正要守的三件事】
/// 1. **数据真的通了**（B3 建的那条链路到底能不能把 Mock 的数据送到界面上）；
/// 2. **不串号**（A 登出、B 登录后看到的必须是 B 的账）；
/// 3. **v1 没有支付**（这一屏不该有任何充值/购买的入口）。
/// ─────────────────────────────────────────────────────────

/// 建一个容器：Mock 服务端 + 内存密钥库，和 `auth_flow_test.dart` 同一套接缝。
ProviderContainer _container({ApiClient? client}) {
  return ProviderContainer.test(
    overrides: [
      appConfigProvider.overrideWithValue(AppConfig.mockOnly),
      apiClientProvider.overrideWithValue(client ?? FakeApiClient()),
      tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
    ],
  );
}

/// 注册一个账号并等它落地。注册会把 token 写进 `authTokenProvider` ——
/// 「我的」页的 provider 靠这个 token 才肯去拉数据。
Future<void> _signUp(
  ProviderContainer container, {
  String username = 'alice',
}) async {
  await container.read(authControllerProvider.notifier).register(
        inviteCode: 'MOCK',
        username: username,
        password: 'pw123456',
      );
}

/// 把整个 App 渲染出来（不是只渲染 AppShell）——
/// 因为「退出登录」这件事的结果是 **home 被换掉**，
/// 只渲染 AppShell 的话根本看不到它。
Future<void> _pumpApp(WidgetTester tester, ProviderContainer container) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const AiVideoApp(),
    ),
  );
  await tester.pumpAndSettle();
}

/// 切到底部某个 Tab。
Future<void> _tapTab(WidgetTester tester, String label) async {
  await tester.tap(
    find.descendant(of: find.byType(GlassTabBar), matching: find.text(label)),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('「我的」页', () {
    testWidgets('显示登录的用户名和注册赠送的积分', (tester) async {
      final container = _container();
      await _signUp(container);
      await _pumpApp(tester, container);

      await _tapTab(tester, '我的');

      expect(find.text('alice'), findsWidgets);
      // 可用积分（注册送 50，没有任何冻结）
      expect(find.text('50'), findsOneWidget);
      // 【这条守的是「不显示一个编出来的数字」】余额拿不到时只能写「计算中…」，
      // 写 0 等于告诉用户「你的积分被清零了」。
      expect(find.text('计算中…'), findsNothing);
    });

    testWidgets('点积分卡片 → 打开积分页', (tester) async {
      final container = _container();
      await _signUp(container);
      await _pumpApp(tester, container);
      await _tapTab(tester, '我的');

      await tester.tap(find.byKey(const Key('me.credits')));
      await tester.pumpAndSettle();

      expect(find.byType(CreditsPage), findsOneWidget);
    });

    testWidgets('点设置 → 打开设置页', (tester) async {
      final container = _container();
      await _signUp(container);
      await _pumpApp(tester, container);
      await _tapTab(tester, '我的');

      await tester.tap(find.byKey(const Key('me.settings')));
      await tester.pumpAndSettle();

      expect(find.byType(SettingsPage), findsOneWidget);
      expect(find.text('版本'), findsOneWidget);
    });
  });

  group('积分页', () {
    testWidgets('显示余额和注册赠送那一条流水', (tester) async {
      final container = _container();
      await _signUp(container);
      await _pumpApp(tester, container);
      await _tapTab(tester, '我的');
      await tester.tap(find.byKey(const Key('me.credits')));
      await tester.pumpAndSettle();

      // 余额：可用 50 / 总额 50 / 冻结 0
      expect(find.text('可用积分'), findsOneWidget);
      expect(find.text('50'), findsWidgets);

      // 流水：备注 + 金额。赠送是**加**，所以带正号。
      expect(find.text('新用户注册赠送'), findsOneWidget);
      expect(find.text('+50'), findsOneWidget);
    });

    testWidgets('v1 没有任何充值 / 购买入口', (tester) async {
      final container = _container();
      await _signUp(container);
      await _pumpApp(tester, container);
      await _tapTab(tester, '我的');
      await tester.tap(find.byKey(const Key('me.credits')));
      await tester.pumpAndSettle();

      // 【§7.6：充值档位标着「v3 预留」】v1 的积分只有一个来源（注册赠送）。
      // 这条断言守的是「别顺手把一个没有对手可以打的支付流程写进来」。
      expect(find.textContaining('充值'), findsNothing);
      expect(find.textContaining('购买'), findsNothing);
      expect(find.textContaining('立即支付'), findsNothing);
      // 计费文案的守卫（§13.4 的另一半：不许出现确定性的花费承诺）
      expect(find.textContaining('预计消耗'), findsNothing);
    });

    testWidgets('流水分页：先 20 条，点「加载更多」再补上剩下的', (tester) async {
      final fake = FakeApiClient();
      final container = _container(client: fake);
      await _signUp(container);

      // 造出 25 条流水：注册那一条 + 24 条调整，正好跨过一页（20）
      for (var i = 0; i < 24; i++) {
        fake.debugGrantCredits(1, note: '调整 $i');
      }

      await _pumpApp(tester, container);
      await _tapTab(tester, '我的');
      await tester.tap(find.byKey(const Key('me.credits')));
      await tester.pumpAndSettle();

      // 第一页只有 20 条，最后一条（调整 0）不该在
      expect(find.text('调整 23'), findsOneWidget);
      expect(find.text('调整 0'), findsNothing);

      // 【为什么要断言「加载更多」还在、还能点】这一页的翻页守卫有三道
      // （没下一页 / 正在拉 / 第一页还没落地），任何一道写反了，
      // 按钮都会变成永远点不动的死按钮。
      //
      // 【⚠️ 必须先 ensureVisible】20 行流水之后这个按钮在屏幕外，
      // 而 `tester.tap` 对屏幕外的 widget **不会报错** ——
      // 它只是把点击事件派发到一个没人的坐标上，打印一行 warning 就过去了。
      // 测试会「通过」，什么都没测到。这是最容易骗过自己的一类假绿。
      final loadMore = find.byKey(const Key('credits.loadMore'));
      expect(loadMore, findsOneWidget);
      await tester.ensureVisible(loadMore);
      await tester.pumpAndSettle();
      await tester.tap(loadMore);
      await tester.pumpAndSettle();

      expect(find.text('调整 0'), findsOneWidget);
      // 25 条正好两页 —— 拉完之后按钮该消失，而不是点了没反应
      expect(find.byKey(const Key('credits.loadMore')), findsNothing);
    });
  });

  group('失败与重试', () {
    testWidgets('拉不到资料 → 显示错误文案，点「重试」能恢复', (tester) async {
      final client = _FlakyClient();
      final container = _container(client: client);
      await _signUp(container);
      // 注册之后开始断网 —— 只断 /me，模拟「服务端只挂了一个接口」
      client.offline = true;

      await _pumpApp(tester, container);
      await _tapTab(tester, '我的');

      // 【为什么断言的是「稍后重试」而不是异常对象】
      // ErrorBox 显示的是 AppException.userMessage，不是 `'$error'`。
      // 把 DioException 之类的字符串丢给用户，除了截图投诉什么也做不了。
      expect(find.textContaining('稍后重试'), findsOneWidget);
      expect(find.byKey(const Key('async.retry')), findsOneWidget);

      client.offline = false;
      await tester.tap(find.byKey(const Key('async.retry')));
      await tester.pumpAndSettle();

      expect(find.text('alice'), findsWidgets);
      expect(find.textContaining('稍后重试'), findsNothing);
    });
  });

  group('换账号', () {
    test('A 登出、B 登录后，「我的」不会再显示 A 的资料', () async {
      final container = _container();
      await _signUp(container, username: 'alice');
      expect((await container.read(meProfileProvider.future)).user.username,
          'alice');

      await container.read(authControllerProvider.notifier).logout();
      await _signUp(container, username: 'bob');

      // 【这条守的是一个不会报错的 bug】
      // 这两个 provider 都是非 autoDispose 的：它们活过整次会话。
      // 如果它们不关心「现在是谁」，B 打开「我的」就会看到**A 的用户名和积分**，
      // 而且没有任何报错 —— 只是数据看着怪。测试里通常只登录一个用户，
      // 所以这种串号极难被发现，必须专门测。
      final profile = await container.read(meProfileProvider.future);
      expect(profile.user.username, 'bob');
      expect(profile.creditAccount.balance, 50);

      final ledger = await container.read(creditLedgerProvider.future);
      expect(ledger.entries, hasLength(1));
    });
  });

  group('退出登录', () {
    testWidgets('从设置页退出 → 回登录页，且设置页不会留在栈上', (tester) async {
      final store = InMemoryTokenStore();
      final container = ProviderContainer.test(
        overrides: [
          appConfigProvider.overrideWithValue(AppConfig.mockOnly),
          apiClientProvider.overrideWithValue(FakeApiClient()),
          tokenStoreProvider.overrideWithValue(store),
        ],
      );
      await _signUp(container);
      await _pumpApp(tester, container);
      expect(find.byType(AppShell), findsOneWidget);

      await _tapTab(tester, '我的');
      await tester.tap(find.byKey(const Key('me.settings')));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsPage), findsOneWidget);

      await tester.tap(find.byKey(const Key('settings.logout')));
      await tester.pumpAndSettle();
      // 先问一句再退 —— 这是这一屏唯一不可撤销的动作
      expect(find.text('取消'), findsOneWidget);

      await tester.tap(find.byKey(const Key('settings.logout.confirm')));
      await tester.pumpAndSettle();

      expect(find.byType(LoginPage), findsOneWidget);
      // 【这条断言就是 `app.dart` 里那个 MaterialApp key 存在的全部理由】
      // 设置页是 push 上来的，它**待在 Navigator 的栈上**。
      // 不换 key 的话，home 被换成登录页而设置页仍压在栈顶 ——
      // 用户明明退出了，看到的还是账号界面。
      expect(find.byType(SettingsPage), findsNothing);
      expect(await store.read(), isNull);
    });

    testWidgets('确认框里点「取消」→ 什么都不发生', (tester) async {
      final store = InMemoryTokenStore();
      final container = ProviderContainer.test(
        overrides: [
          appConfigProvider.overrideWithValue(AppConfig.mockOnly),
          apiClientProvider.overrideWithValue(FakeApiClient()),
          tokenStoreProvider.overrideWithValue(store),
        ],
      );
      await _signUp(container);
      await _pumpApp(tester, container);
      await _tapTab(tester, '我的');
      await tester.tap(find.byKey(const Key('me.settings')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('settings.logout')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();

      // 【为什么这条不能省】确认框写反了（把「取消」接成登出）是
      // 一次误触就会发生的事故，而上面那条测试**发现不了**它。
      expect(find.byType(SettingsPage), findsOneWidget);
      expect(await store.read(), isNotNull);
    });
  });
}

/// 只对某几个接口断网的假服务端。
///
/// 【为什么要在 ApiClient 这层做，而不是换一个假 repository】
/// 因为「网络挂了」是一件**发生在通信层**的事。换掉 repository 会把
/// 错误码映射、异常类型转换一起绕过去，那测出来的错误态就不是真实会出现的那个。
/// 装饰真实的 [FakeApiClient]，只让它对指定路径抛错 —— 上面所有层原样跑。
class _FlakyClient implements ApiClient {
  final FakeApiClient _inner = FakeApiClient();

  /// 为 true 时，`/me` 和积分流水都当作断网。
  bool offline = false;

  static const _broken = {'/me', '/credits/ledger'};

  Future<Map<String, dynamic>> _guard(
    String path,
    Future<Map<String, dynamic>> Function() run,
  ) {
    if (offline && _broken.contains(path)) {
      throw AppException.network('测试里故意断的');
    }
    return run();
  }

  @override
  Future<Map<String, dynamic>> get(String path, {Map<String, dynamic>? query}) =>
      _guard(path, () => _inner.get(path, query: query));

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body}) =>
      _guard(path, () => _inner.post(path, body: body));

  @override
  Future<Map<String, dynamic>> delete(String path) =>
      _guard(path, () => _inner.delete(path));

  @override
  Future<Map<String, dynamic>> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    String? mimeType,
  }) =>
      _guard(
        path,
        () => _inner.upload(
          path,
          bytes: bytes,
          filename: filename,
          mimeType: mimeType,
        ),
      );
}
