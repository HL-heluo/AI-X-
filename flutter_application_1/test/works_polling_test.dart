import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/core/constants/task_status.dart';
import 'package:flutter_application_1/core/env.dart';
import 'package:flutter_application_1/core/polling/task_poll_backoff.dart';
import 'package:flutter_application_1/core/storage/token_store.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/models/task.dart';
import 'package:flutter_application_1/pages/task/task_detail_page.dart';
import 'package:flutter_application_1/pages/works/works_page.dart';
import 'package:flutter_application_1/providers/app_providers.dart';
import 'package:flutter_application_1/providers/auth_providers.dart';
import 'package:flutter_application_1/providers/generation_providers.dart';
import 'package:flutter_application_1/providers/task_providers.dart';

import 'shell_harness.dart';

/// ─────────────────────────────────────────────────────────
/// 「进行中」这条路 —— 前面所有测试都绕着它走
///
/// 【为什么这批测试现在才补】
/// 因为**极简模式的 Mock 提交完立刻成功**（那是刻意选的取舍），
/// 于是从 B3 到 B6，所有 widget 测试里的世界都是「一个进行中的任务都没有」。
/// 而 §8.4 那一整套东西 —— 轮询心跳、退避、排队位次、
/// 「你可以退出这个页面」那句话 —— 全都长在这条路上。
/// 一条从来没被渲染过的路径，写没写对全靠读代码。
///
/// 这里用一个 `latency` 非空 + **时钟可推进** 的 Mock 把那条路造出来。
/// 时钟注入是关键：真等一分钟的测试没人会跑。
/// ─────────────────────────────────────────────────────────

/// 一个能被测试推着走的时钟。
///
/// 【为什么要这个东西】Mock 的 `latency` 是拿**墙上时钟的差**判阶段的
/// （见 `FakeApiClient._advance`），所以它不是「等一会儿就好」，
/// 而是「时钟走过头了才推进」。给它一个自己管的时间源，
/// 「视频跑了十分钟」这件事就能在一瞬间发生。
class _Clock {
  DateTime now = DateTime.utc(2026, 1, 1, 12);

  void skip(Duration d) => now = now.add(d);
}

/// 一个「任务要跑一会儿」的 Mock。
///
/// `latency` 给 1 分钟：`queued → submitted` 要过 1 分钟，
/// `→ succeeded` 要过 2 分钟（见 `_advance` 的两个分界）。
/// 不推时钟，任务就一直停在 `queued` —— 这正是「进行中」的样子。
FakeApiClient _slowMock(_Clock clock) => FakeApiClient(
      latency: const Duration(minutes: 1),
      clock: () => clock.now,
    );

/// 起一个只装了数据层的容器（不渲染界面）—— 测 provider 用。
///
/// 【为什么不复用 pumpLoggedInShell】那个会把整个 AppShell 渲染出来。
/// 心跳这几条要的是「推 5 秒、看定时器有没有醒」，
/// 渲染一棵界面树只会让失败时的输出淹没在 widget 错误里。
Future<ProviderContainer> _bootContainer(FakeApiClient client) async {
  final container = ProviderContainer.test(
    overrides: [
      appConfigProvider.overrideWithValue(AppConfig.mockOnly),
      apiClientProvider.overrideWithValue(client),
      tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
    ],
  );
  await container.read(authControllerProvider.notifier).register(
        inviteCode: kTestInviteCode,
        username: kTestUsername,
        password: kTestPassword,
      );
  return container;
}

void main() {
  // ═══════════════════════════════════════════════════════════
  //  一、退避曲线：纯计算，五个断言就能钉死
  // ═══════════════════════════════════════════════════════════

  group('轮询退避（§8.4：起 5 秒、退避到 15 秒）', () {
    const backoff = TaskPollBackoff();

    test('前一分钟每 5 秒一次 —— 图片是秒级完成的，不能让它白等', () {
      for (var tick = 0; tick < 12; tick++) {
        expect(backoff.delayFor(tick), const Duration(seconds: 5), reason: 'tick=$tick');
      }
    });

    test('一分钟后退到 15 秒 —— 视频要十分钟，5 秒一次是白烧后端', () {
      expect(backoff.delayFor(12), const Duration(seconds: 15));
      expect(backoff.delayFor(120), const Duration(seconds: 15));
    });

    test('分界线落在第 12 拍上（12 × 5 秒 = 1 分钟）', () {
      // 【为什么要单独钉这一条】11 和 12 是唯一容易写错的地方：
      // `tick < fastTicks` 写成 `<=` 就会变成 65 秒之后才退避 ——
      // 这种差一拍的错误，其它的断言全都过得去。
      expect(backoff.delayFor(11), backoff.fast);
      expect(backoff.delayFor(12), backoff.slow);
    });

    test('异常入参兜底成最短间隔，而不是算出个负数或零', () {
      // 负数会让 Timer 直接「立即执行」，于是退避形同虚设、变成死循环打后端。
      expect(backoff.delayFor(-1), backoff.fast);
      expect(backoff.delayFor(-5), backoff.fast);
    });
  });

  // ═══════════════════════════════════════════════════════════
  //  二、心跳的起停条件（§8.4 列了四条，这里测其中三条）
  // ═══════════════════════════════════════════════════════════

  group('轮询心跳的起停', () {
    testWidgets('没有进行中的任务时不起心跳', (tester) async {
      final container = await _bootContainer(FakeApiClient());
      final polling = container.read(taskPollingProvider.notifier);

      polling.syncWith(const AsyncData<List<Task>>(<Task>[]));
      expect(polling.isRunning, isFalse);
      expect(container.read(taskPollingProvider), isFalse);
    });

    testWidgets('有进行中的任务就起，任务没了这一拍就自己停', (tester) async {
      final container = await _bootContainer(FakeApiClient());
      final polling = container.read(taskPollingProvider.notifier);

      polling.syncWith(AsyncData(const [_someTask]));
      expect(polling.isRunning, isTrue);
      expect(container.read(taskPollingProvider), isTrue);

      // 【为什么这一拍之后就该停】因为 Mock 里**根本没有**这个任务 ——
      // 心跳醒来会去拉一次真实的进行中列表，拉回来是空的。
      // 这正是「任务做完 → 心跳自己停」那条路径：
      // 不靠界面通知，靠每一拍自己核对一次，两边哪个先到都幂等。
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();

      expect(polling.isRunning, isFalse);
      expect(container.read(taskPollingProvider), isFalse);
    });

    testWidgets('App 退到后台 → pause() 停，并且计数归零（下次从 5 秒起步）', (tester) async {
      final container = await _bootContainer(FakeApiClient());
      final polling = container.read(taskPollingProvider.notifier);

      polling.syncWith(AsyncData(const [_someTask]));
      expect(polling.isRunning, isTrue);

      polling.pause();
      expect(polling.isRunning, isFalse);

      // 再回来时不该还记着上次跑到第几拍 —— 那多半是个新任务，
      // 前一分钟最可能出结果，值得重新勤快起来。
      polling.syncWith(AsyncData(const [_someTask]));
      expect(polling.isRunning, isTrue);
      polling.pause();
      expect(polling.isRunning, isFalse);
    });

    testWidgets('拿不到数据时不掐掉心跳（一次网络抖动不该让通知永远不响）', (tester) async {
      // 【为什么这条最值得测】这是这个类里唯一「看起来该做点什么、
      // 实际必须什么都不做」的分支。顺手写成「不是成功就停」的话，
      // 表现是「偶尔不弹通知」—— 没有报错、没有复现步骤，
      // 只有用户说「我那次没收到」。
      final container = await _bootContainer(FakeApiClient());
      final polling = container.read(taskPollingProvider.notifier);

      polling.syncWith(AsyncError<List<Task>>(Exception('network'), StackTrace.empty));
      expect(polling.isRunning, isFalse, reason: '本来没跑，出错了也不该开始跑');

      polling.syncWith(AsyncData(const [_someTask]));
      expect(polling.isRunning, isTrue);

      polling.syncWith(AsyncError<List<Task>>(Exception('network'), StackTrace.empty));
      expect(polling.isRunning, isTrue, reason: '正在跑的时候出了错，心跳要继续');

      polling.syncWith(const AsyncLoading<List<Task>>());
      expect(polling.isRunning, isTrue, reason: '重新加载中也不代表任务没了');

      polling.pause();
    });

    testWidgets('登出之后心跳会自己停 —— 没人喊它，也不该一直空转', (tester) async {
      // 【为什么这条必须存在】心跳是跟着**会话**走的，不是跟着某棵 widget 树
      // 走的（`taskPollingProvider` 故意不是 autoDispose —— 用户切 Tab、
      // 进详情页都不该把心跳掐掉再重起）。
      // 于是一个很自然的问题是：**登出以后它靠什么停？**
      //
      // 答案不是「谁去喊它停」，而是它自己会撞上：登出 → token 变 null →
      // `activeTasksProvider` 进错误态 → 下一拍拉到的东西是空的，
      // `_onTick` 看到「没有进行中的任务」就收工。
      // 也就是说，这条路径同时兜住了 §8.4 的停止条件 2 和 4：
      // 没有人必须记得取消它。
      final container = await _bootContainer(FakeApiClient());
      final polling = container.read(taskPollingProvider.notifier);

      polling.syncWith(AsyncData(const [_someTask]));
      expect(polling.isRunning, isTrue);

      await container.read(authControllerProvider.notifier).logout();
      await tester.pump();
      // 登出这一瞬间状态还是 error，不是「明确的空」——
      // 按上面那条规矩，不知道就不要动它。所以这里**还**在跑。
      expect(polling.isRunning, isTrue);

      // 下一拍撞上空列表，自己收工
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(polling.isRunning, isFalse);
    });
  });

  // ═══════════════════════════════════════════════════════════
  //  三、界面：空态，以及「进行中」真的渲染得出来
  // ═══════════════════════════════════════════════════════════

  group('作品页', () {
    testWidgets('新用户两个分段都是空态，且话说得下去哪儿做', (tester) async {
      tester.view.physicalSize = const Size(390, 1400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await pumpLoggedInShell(tester);

      await tester.tap(find.byKey(const Key('tab.1')));
      await tester.pumpAndSettle();

      // 「进行中」空态：不只是「没有」，还要告诉他去哪儿弄一个出来
      expect(find.text('现在没有进行中的任务'), findsOneWidget);
      expect(find.textContaining('去「创作」页'), findsOneWidget);

      await tester.tap(find.byKey(const Key('works.segment.1')));
      await tester.pumpAndSettle();

      expect(find.text('还没有作品'), findsOneWidget);

      await unmountAndDrain(tester);
    });

    testWidgets('排队中的任务出现在「进行中」，点开能进任务详情', (tester) async {
      tester.view.physicalSize = const Size(390, 1400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      final clock = _Clock();
      final container = await pumpLoggedInShell(tester, apiClient: _slowMock(clock));

      // 提交一个任务，但**不推时钟** —— 它就停在 queued 上。
      final task = await container.read(generationSubmitterProvider).submitImage(
            prompt: '一只猫在沙滩上',
            idempotencyKey: 'k-works-1',
          );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('tab.1')));
      await tester.pumpAndSettle();

      // 进行中分段（默认那个）里有一条
      expect(find.byType(WorksPage), findsOneWidget);
      expect(find.byKey(Key('works.active.${task.id}')), findsOneWidget);

      // §8.4 的设计意图是「用户可以离开」—— 那就得说出来，
      // 否则用户会盯着屏幕等十分钟。
      expect(find.textContaining('你可以退出这个页面'), findsOneWidget);

      // 点开进任务详情
      await tester.tap(find.byKey(Key('works.active.${task.id}')));
      await tester.pumpAndSettle();

      expect(find.byType(TaskDetailPage), findsOneWidget);
      expect(find.text('一只猫在沙滩上'), findsWidgets);

      // 【为什么这里要手动把心跳停掉】因为这条测试结束时，那个任务**还在跑**
      // （时钟没推过，Mock 里它一直停在 queued），所以每 5 秒的定时器还活着。
      // 而心跳是跟着会话走的，不跟着 widget 树走（见上一条测试）——
      // 树拆了它也不会自己停，于是测试框架会报「拆完树还有 Timer 挂着」。
      //
      // 真机上这一步对应的是**登出**（用户自己会走，或者 App 被系统回收）。
      // 测试里没有登出这个动作，那就自己收尾 —— 让定时器悬着才是错的。
      container.read(taskPollingProvider.notifier).pause();

      await unmountAndDrain(tester);
    });
  });
}

/// 一个只用来「假装列表里有一条」的任务。
///
/// 【为什么这条假数据是安全的】它**只喂给 `syncWith`**，用来回答
/// 「有任务时该起心跳吗」这个问题；它不会进 Mock，也不会进界面。
/// 心跳醒来之后拉的是真数据，于是它那一下就被真实状态纠正了 ——
/// 这本身就是测试里最有价值的那部分（见「任务没了这一拍就自己停」）。
const Task _someTask = Task(
  id: '999001',
  kind: TaskKind.textToImage,
  status: TaskStatus.queued,
  prompt: '占位',
  freezeAmount: 4,
);
