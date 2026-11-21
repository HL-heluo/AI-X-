import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/app.dart';
import 'package:flutter_application_1/core/constants/api_paths.dart';
import 'package:flutter_application_1/core/env.dart';
import 'package:flutter_application_1/core/network/api_client.dart';
import 'package:flutter_application_1/core/storage/token_store.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/pages/credits/credits_page.dart';
import 'package:flutter_application_1/providers/app_providers.dart';
import 'package:flutter_application_1/providers/auth_providers.dart';
import 'package:flutter_application_1/widgets/glass_tab_bar.dart';

/// ─────────────────────────────────────────────────────────
/// 「积分明细 → 链上凭证」里的一键复制。
///
/// 【为什么这条值得单独测】
/// 那个复制按钮的存在理由是「用户要拿地址去 Remix / 区块浏览器自己核对」。
/// 它有两个**不会报错**的坏法：
/// 1. 复制进剪贴板的是**截断后的显示文本**（`0x90F8…8c9C1`）而不是完整地址
///    —— 界面看着一切正常，粘到 Remix 里就是查不到；
/// 2. 复制了，但**没给任何反馈** —— 用户不知道成功没有，会连点五下。
/// 这两种都不会崩、不会红，只能靠断言「写进剪贴板的到底是什么」来守。
/// ─────────────────────────────────────────────────────────

/// 真实地址的形状：`0x` + 40 位十六进制。用真的长度，别用假的短串 ——
/// 截断 bug 只有在地址够长时才会显形。
const String _wallet = '0x90F8bf6A479f320ead074411a4B0e7944Ea8c9C1';
const String _contract = '0x67B5656d60a809915323Bf2C40A8bEF15A152e3e';

/// 让 Mock 服务端「假装影子链开着」，**只改 `/credits/chain` 一个接口**。
///
/// 【为什么装饰 ApiClient 而不是换掉 repository】和 `me_credits_test.dart`
/// 里 `_FlakyClient` 同一个理由：换掉 repository 会绕过异常映射，
/// 而这里要测的是「界面拿到一份真实的 ChainSummary 之后的行为」，
/// 越靠下改越好 —— 上面所有层原样跑。
class _ChainClient implements ApiClient {
  final FakeApiClient _inner = FakeApiClient();

  @override
  Future<Map<String, dynamic>> get(String path, {Map<String, dynamic>? query}) {
    if (path == ApiPaths.creditChain) {
      return Future<Map<String, dynamic>>.value(<String, dynamic>{
        'enabled': true,
        'rpc': 'http://127.0.0.1:8545',
        'contract': _contract,
        'address': _wallet,
        'on_chain_balance': 22,
        'ledger_balance': 22,
        'total_supply': 212,
        'recent_ops': <Object>[],
      });
    }
    return _inner.get(path, query: query);
  }

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body}) =>
      _inner.post(path, body: body);

  @override
  Future<Map<String, dynamic>> delete(String path) => _inner.delete(path);

  @override
  Future<Map<String, dynamic>> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    String? mimeType,
  }) =>
      _inner.upload(
        path,
        bytes: bytes,
        filename: filename,
        mimeType: mimeType,
      );
}

void main() {
  testWidgets('积分明细的链上凭证：钱包 / 合约地址都能一键复制完整地址', (tester) async {
    // ── 把剪贴板这次平台调用拦下来，记下真正写进去的文本 ──
    // 不装这个 handler 的话，`Clipboard.setData` 在测试里没有实现，
    // 「复制了什么」就无从断言 —— 那样这条测试只能证明「按钮没崩」。
    final copied = <String>[];
    final binding = TestDefaultBinaryMessengerBinding.instance;
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          final args = call.arguments as Map<Object?, Object?>;
          copied.add(args['text']! as String);
        }
        return null;
      },
    );
    addTearDown(
      () => binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null),
    );

    final container = ProviderContainer.test(
      overrides: [
        appConfigProvider.overrideWithValue(AppConfig.mockOnly),
        apiClientProvider.overrideWithValue(_ChainClient()),
        tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
      ],
    );
    await container.read(authControllerProvider.notifier).register(
          inviteCode: 'MOCK',
          username: 'alice',
          password: 'pw123456',
        );

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const AiVideoApp(),
      ),
    );
    await tester.pumpAndSettle();

    // 「我的」→ 积分明细
    await tester.tap(
      find.descendant(of: find.byType(GlassTabBar), matching: find.text('我的')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('me.credits')));
    await tester.pumpAndSettle();

    expect(find.byType(CreditsPage), findsOneWidget);
    // 界面上是**完整**地址（不是 `0x90F8…8c9C1`）——
    // 显示截断、复制完整也能用，但显示和复制不一致会让人怀疑抄错了。
    expect(find.text(_wallet), findsOneWidget);
    expect(find.text(_contract), findsOneWidget);

    final copyWallet = find.byKey(const Key('credits.copyWallet'));
    final copyContract = find.byKey(const Key('credits.copyContract'));
    expect(copyWallet, findsOneWidget);
    expect(copyContract, findsOneWidget);

    // 【必须 ensureVisible】对屏幕外的 widget 调 `tester.tap` **不会报错**，
    // 它只是把点击派发到一个没人的坐标上，打印一行 warning 就过去了 ——
    // 测试会「通过」，其实什么都没测到。
    await tester.ensureVisible(copyWallet);
    await tester.pumpAndSettle();
    await tester.tap(copyWallet);
    await tester.pumpAndSettle();

    await tester.ensureVisible(copyContract);
    await tester.pumpAndSettle();
    await tester.tap(copyContract);
    await tester.pumpAndSettle();

    // 关键断言：写进剪贴板的是完整地址，且两次分别对应「钱包」「合约」。
    // 顺序写反（把合约按钮接到钱包的值上）就是因为这个列表才对得上。
    expect(copied, <String>[_wallet, _contract]);

    // 复制完必须有可见反馈，否则用户不知道成没成。
    expect(find.textContaining('地址已复制'), findsWidgets);
  });
}
