import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'pages/create/create_page.dart';
import 'pages/marketplace/marketplace_page.dart';
import 'pages/me/me_page.dart';
import 'pages/works/works_page.dart';
import 'providers/shell_providers.dart';
import 'providers/task_providers.dart';
import 'widgets/app_background.dart';
import 'widgets/glass_tab_bar.dart';

/// 底部导航和任务轮询共用的 App 外壳。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么任务轮询放在外壳】
///
/// 心跳挂这里不是随手放的，是 §8.4 逼出来的一个位置：
/// 「视频约 10 分钟，用户可以离开那一屏」—— 那就意味着轮询**不能**
/// 挂在「作品」页上。用户切到「我的」看了两眼积分，轮询跟着页面一起没了，
/// 十分钟后任务完成：通知不响、进度不动、他回来还得手动刷。
///
/// 挂在底部导航的公共外壳上，只要有人在登录状态里，心跳就在。
///
/// 【为什么选中项从 State 搬到了 provider】
/// 见 `selectedTabProvider` 的注释：首页的「全部 ›」要切到第 2 个 Tab，
/// 而首页不是外壳，拿不到外壳的 State。
///
/// 【为什么是 ConsumerStatefulWidget 而不是 ConsumerWidget】
/// 因为要挂**生命周期回调**（App 退到后台就把心跳停掉，回前台再起来）。
/// 那是 `State` 才有的钩子。
/// ─────────────────────────────────────────────────────────
class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    // 用 WidgetsBindingObserver 而不是 AppLifecycleListener：
    // 前者在 Flutter 里更老、更稳，而且和 `didChangeAppLifecycleState`
    // 一比一对得上。这里只需要一个「前后台」的开关，不需要新 API 的能力。
    WidgetsBinding.instance.addObserver(this);

    // 先把「进行中」拉起来。下面 build 里的 `ref.listen` 只对**变化**触发，
    // 不先创建它的话，冷启动的第一轮数据要等下一次变化才有人接 ——
    // 而那时候可能已经没有任务了。
    ref.read(activeTasksProvider);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // ─────────────────────────────────────────────────────────
    // 【为什么要管这件事，而不让轮询一直跑】
    //
    // 用户把 App 切到后台，可能十分钟后才回来。这十分钟里每 5~15 秒
    // 发一个请求，是**纯浪费**：电、流量、后端配额。而 §7.5 的四道闸
    // 是按账号算配额的，这些请求会实打实地占掉别人的额度。
    //
    // 【为什么回到前台要 `refresh` + `syncWith` 两步】
    //
    // 光靠「重新开始轮询」是不够的：后台这十分钟里任务可能**已经做完了**，
    // 而手上的列表还是旧的。所以先把「进行中」重拉一次（不 await ——
    // 用户已经在看屏幕了，别让他等），再拿着**当前**这份值决定要不要起心跳。
    //
    // 两步的顺序不能反：先 refresh 的话，它的结果会通过 `ref.listen`
    // 再触发一次 `syncWith`，两边是幂等的（`_schedule` 里
    // `if (_timer != null) return;`）。反过来则会出现「用旧数据起了心跳，
    // 新数据回来又停掉」的一次抖动。
    // ─────────────────────────────────────────────────────────
    if (state == AppLifecycleState.resumed) {
      ref.read(activeTasksProvider.notifier).refresh();
      ref
          .read(taskPollingProvider.notifier)
          .syncWith(ref.read(activeTasksProvider));
      return;
    }

    ref.read(taskPollingProvider.notifier).pause();
  }

  @override
  Widget build(BuildContext context) {
    final currentIndex = ref.watch(selectedTabProvider);

    // ─────────────────────────────────────────────────────────
    // 【心跳的开关：跟着「有没有进行中的任务」走】
    //
    // 只需要接住**变化**就够了：冷启动那一次由 `initState` 里的
    // `ref.read(activeTasksProvider)` 触发，数据回来就是一次变化。
    //
    // 【为什么没有任务时必须停】一个空列表还在每 5 秒问一次，
    // 是这个 App 最容易被后端骂的一种行为。`syncWith` 收到空列表就取消定时器。
    // ─────────────────────────────────────────────────────────
    ref.listen(activeTasksProvider, (previous, next) {
      ref.read(taskPollingProvider.notifier).syncWith(next);
    });

    return AppBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1080),
            child: IndexedStack(
              index: currentIndex,
              sizing: StackFit.expand,
              children: [
                const CreatePage(),
                const WorksPage(),
                Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 780),
                    child: MarketplacePage(
                      active:
                          currentIndex == SelectedTabNotifier.marketplaceTab,
                    ),
                  ),
                ),
                Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 680),
                    child: const MePage(),
                  ),
                ),
              ],
            ),
          ),
        ),
        bottomNavigationBar: GlassTabBar(
          currentIndex: currentIndex,
          onTap: (i) => ref.read(selectedTabProvider.notifier).select(i),
        ),
      ),
    );
  }
}
