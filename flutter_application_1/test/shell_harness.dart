import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/app_shell.dart';
import 'package:flutter_application_1/core/env.dart';
import 'package:flutter_application_1/core/network/api_client.dart';
import 'package:flutter_application_1/core/storage/token_store.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/providers/app_providers.dart';
import 'package:flutter_application_1/providers/auth_providers.dart';
import 'package:flutter_application_1/theme/app_theme.dart';

/// 把 `AppShell` **当成已登录**渲染出来，返回它背后的容器。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么冒烟测试需要这个，之前却不需要】
///
/// B5 之前，`AppShell` 里三个页面都是纯静态的占位，谁都不碰 provider ——
/// 所以 `pumpWidget(MaterialApp(home: AppShell()))` 就够了。
///
/// B5 之后「我的」页要 `ref.watch(meProfileProvider)`。没有 [ProviderScope]
/// 时它会直接抛「No ProviderScope found」，**三个页面一起挂**；
/// 就算套了空 scope，`meProfileProvider` 也会因为没有 token 而进错误态 ——
/// 冒烟测试就变成了在测「错误提示长得对不对」。
///
/// 【为什么要真的走一次注册，而不是随便塞个 token】
/// 因为 `AppShell` 只在登录态下存在。真注册一次，才能拿到一条
/// **真实的**登录态：token 被发出去、`authTokenProvider` 被写入、
/// 赠送的积分和流水真的在 Mock 里生成。测试里少造一样假东西，
/// 就少一处「测试过了但真机不对」。
///
/// 【登录的账号是哪个】
/// 用户名固定 `alice`，密码 `pw123456`，邀请码 `MOCK` ——
/// 和 `auth_flow_test.dart` 里用的是同一套，方便对照着看。
///
/// 【为什么要能换一个 apiClient 进来】默认那个 `FakeApiClient()` 是
/// **提交即成功**的极简模式，也就是「永远没有进行中的任务」——
/// 于是「进行中」这一整条路径（排队位次、轮询心跳、取消按钮）
/// 在测试里从来没被渲染过。想看它，就得塞一个 `latency` 非空、
/// 并且时钟可以被测试推着走的 Mock 进来。
const String kTestUsername = 'alice';
const String kTestPassword = 'pw123456';
const String kTestInviteCode = 'MOCK';

Future<ProviderContainer> pumpLoggedInShell(
  WidgetTester tester, {
  /// 不传就是极简模式（立刻完成）。要看「进行中」，传
  /// `FakeApiClient(latency: ..., clock: ...)`。
  ApiClient? apiClient,
}) async {
  final container = ProviderContainer.test(
    overrides: [
      appConfigProvider.overrideWithValue(AppConfig.mockOnly),
      apiClientProvider.overrideWithValue(apiClient ?? FakeApiClient()),
      tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
    ],
  );

  // 【为什么要先 await 这一次注册】它会把 token 写进 `authTokenProvider`，
  // 而「我的」页的 provider 正是靠这个 token 才肯去拉数据。
  // 顺序反了的话，第一次渲染拿到的是「未登录」的错误态。
  await container.read(authControllerProvider.notifier).register(
        inviteCode: kTestInviteCode,
        username: kTestUsername,
        password: kTestPassword,
      );

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: AppTheme.light, home: const AppShell()),
    ),
  );
  // 等三页里所有异步 provider 落地（「我的」页会发一次 /me）
  await tester.pumpAndSettle();

  return container;
}

/// 拆掉 widget 树，并把「拆树时排下的收尾任务」跑干净。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么挂过 AppShell 的测试，结尾都要加这一句】
///
/// 因为首页现在会 `ref.watch` 一个 **autoDispose** 的 provider
/// （`costEstimateProvider` —— 生成按钮下面那句报价）。
///
/// Riverpod 3 的 autoDispose 不是「没听众就地销毁」，而是
/// **排一个零延时的定时器**稍后销毁（`ProviderScheduler.scheduleProviderDispose`）。
/// 而 `flutter_test` 拆树是在**测试函数体之后**、由测试框架自己做，
/// 拆完只 `pump()` 一帧、不推进假时钟 —— 那个零延时的定时器就一直挂着，
/// 于是报错：
///
///     A Timer is still pending even after the widget tree was disposed.
///
/// 【这条报错为什么特别难查】它长得像「你忘了取消一个 Timer」，
/// 于是很自然会去翻自己写的 `Timer` / 动画 / 流订阅 ——
/// 而真正的来源是 Riverpod 的内部调度，和业务代码一行关系都没有。
/// 表现上还特别随机：只有**挂过首页**（或任何 watch 了 autoDispose
/// provider 的页面）的测试才会中，别的测试全绿。
///
/// 【为什么解法是「在测试体里自己拆树」】因为只有测试体内部才有机会
/// 在拆树之后**再 pump 一次并推进时钟**。卸载之后 `pumpAndSettle()`
/// 会把那一串零延时的销毁任务全部跑完（它们还可能级联出新的销毁任务）。
/// ─────────────────────────────────────────────────────────
Future<void> unmountAndDrain(WidgetTester tester) async {
  // 换成一棵空树 = 卸载原来的整棵树（和框架自己做的事一样，只是提前了）
  await tester.pumpWidget(const SizedBox.shrink());
  // 推进时钟，让 Riverpod 排下的零延时销毁任务真的跑掉。
  // 用 pumpAndSettle 而不是 pump(1ms)：销毁可能级联（A 销毁 → B 没人听了 → B 也排销毁）。
  await tester.pumpAndSettle();
}
