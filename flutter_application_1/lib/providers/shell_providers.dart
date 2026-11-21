import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app_providers.dart';

/// 底部 Tab 当前选中第几个
///
/// ─────────────────────────────────────────────────────────
/// 【为什么它从 AppShell 的 State 里搬出来了】
///
/// 原本 `_AppShellState` 用一个 `int _currentIndex` 管这件事，够用 ——
/// 直到首页的「最近作品」需要一个能用的「全部 ›」按钮。
/// 那个按钮要跳到的正是第 2 个 Tab，而 Tab 的选中状态住在
/// AppShell 的 State 里，**首页拿不到**。
///
/// 当时有三条路：
///   1. 给「最近作品」传一个回调，一路从 AppShell 穿到第四层子组件；
///   2. 把「全部 ›」做成一个只会 push 的作品页（不走 Tab）；
///   3. 把选中项提成一个 provider。
///
/// 选 3。理由：路 1 会让「首页的某个子组件需要知道外壳的事」变成常态，
/// 下一处再需要的时候又是一条回调链；路 2 会造出「点『全部』进去的页面
/// 没有底部 Tab 栏，点底部 Tab 进去的有」这种不一致 ——
/// 同一件东西两个入口长得不一样，是最容易被用户当成 bug 的一类不一致。
/// ─────────────────────────────────────────────────────────
///
/// 【为什么 build 里要 watch token】
/// 这个 provider 活过整次会话，而 `app.dart` 是靠换 MaterialApp 的 key
/// 来清空导航栈的 —— 那只重建了 widget 树，**不会重置 provider**。
/// 所以不加这一句的话：用户在「作品」Tab 上退出登录、换个人登录，
/// 新用户一进来看到的就是作品页。见 `auth_providers.dart` 末尾那条规矩。
class SelectedTabNotifier extends Notifier<int> {
  /// 「创作」是第 0 个。第一屏应当是创作（§13.2 的主线顺序）。
  static const int createTab = 0;
  static const int worksTab = 1;
  static const int marketplaceTab = 2;
  static const int meTab = 3;

  @override
  int build() {
    // 换个人 → 回到创作页
    ref.watch(authTokenProvider);
    return createTab;
  }

  /// 切到第 [index] 个 Tab。
  void select(int index) {
    // 【为什么要挡一下】同一个值重复赋值会让所有 watch 它的组件白重建一次，
    // 而 SetState 那套「点当前 Tab 就滚回顶部」的行为这里暂时不做 ——
    // 与其留一个没人接的信号，不如让重复点击彻底无事发生。
    if (state == index) return;
    state = index;
  }
}

final selectedTabProvider = NotifierProvider<SelectedTabNotifier, int>(
  SelectedTabNotifier.new,
);

/// 作品页当前看的是哪一段：0 = 进行中，1 = 已完成。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么它也从 WorksPage 的 State 里搬了出来】
///
/// 和 [selectedTabProvider] 是同一个理由，同一个下午发现的：
/// 首页的「最近作品」右边有一个「全部 ›」，它要做的是
/// **切到作品 Tab 的「已完成」分段**。
///
/// 「切到哪个 Tab」能通过 provider 解决（见上），但落在那一页上时
/// 用户看到的还是「进行中」——而那个分段在大多数时候是空的。
/// 于是他会收到一个这样的体验：点「全部」→ 跳到一个写着
/// 「现在没有进行中的任务」的页面。他只会认为自己的作品没了。
///
/// 【为什么不能像 Tab 那样「用回调传进去」】
/// 回调链解决的是「父 → 子」的通知；这里是**别的页面**要写这一页的状态，
/// 中间还隔着 IndexedStack 和 Tab 栏，传不下去。
///
/// 【注意这不是任务状态】它只是「现在看哪一段」——
/// 和任务的真实状态无关（那些一律在服务端，见 §8.4）。
/// 换句话说，把它初始化成「已完成」不会让任何数据出错。
/// ─────────────────────────────────────────────────────────
class WorksSegmentNotifier extends Notifier<int> {
  static const int active = 0;
  static const int done = 1;

  @override
  int build() {
    // 【为什么要 watch token】和 [SelectedTabNotifier] 一字不差的原因：
    // 这个 provider 活过整次会话，而换用户只是重建 widget 树，
    // 不会重置 provider。不 watch 的话，上一个用户停在「已完成」，
    // 新用户一进来看到的也是「已完成」—— 一个和别人有关的位置。
    ref.watch(authTokenProvider);
    return active;
  }

  void select(int index) {
    // 同一个值重复赋值会让所有 watch 它的组件白重建一次（见 SelectedTabNotifier）
    if (state == index) return;
    state = index;
  }
}

final worksSegmentProvider = NotifierProvider<WorksSegmentNotifier, int>(
  WorksSegmentNotifier.new,
);
