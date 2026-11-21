import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../core/notifications/local_task_notifier.dart';
import '../core/notifications/task_notifier.dart';
import '../core/polling/task_poll_backoff.dart';
import '../models/task.dart';
import 'app_providers.dart';
import 'asset_providers.dart';
import 'me_providers.dart';

/// 进行中的任务（`GET /tasks?status=active`）
///
/// ─────────────────────────────────────────────────────────
/// 【这个 provider 就是 §8.4 那条硬规则的执行体】
///
/// §8.4：「任务生命周期完全归服务端，客户端只是观察者。**绝不**把任务状态
/// 存在 App 内存里；App 重开必须能从服务端拉回全部进行中任务。」
///
/// 所以：首页的「进行中任务条」和作品页的「进行中」分段**都读它**，
/// 而它每次 build 都真的去打一次服务端。没有任何一层「缓存一份任务状态
/// 免得每次都拉」—— 那正是被禁止的事。
///
/// 【为什么 build 里必须 watch authTokenProvider】
/// 见 `me_providers.dart` 里那段完整说明。一句话版本：
/// 不 watch 的话，A 登出、B 登录之后，B 会在首页看到 **A 正在跑的任务**。
///
/// 【为什么不是 StreamProvider】
/// 因为轮询的节奏要由我们控制（5 秒 → 15 秒退避、暂停时停、没有任务时停），
/// 而 stream 的节奏由产生它的人控制。这里需要的是「什么时候问」这件事
/// 捏在自己手里，所以是 `Timer` + `refresh`（见 [TaskPollingController]）。
/// ─────────────────────────────────────────────────────────
class ActiveTasksNotifier extends AsyncNotifier<List<Task>> {
  @override
  Future<List<Task>> build() {
    // 【为什么要 watch token 而不是 read】watch 才能让「换了个人」这件事
    // 自动作废这份缓存。详见 auth_providers.dart 末尾那段规矩。
    final token = ref.watch(authTokenProvider);
    if (token == null) throw AppException.unauthorized();

    return ref.read(taskRepositoryProvider).fetchActive();
  }

  /// 重新拉一次（下拉刷新、提交成功后、取消任务后）。
  Future<void> refresh() async {
    // 【为什么只在「手上什么都没有」时才切 loading】下拉刷新的指示器
    // 自己就在转，再切一次骨架会让内容闪一下；而「失败后点重试」时
    // 屏幕上只有一句错误，不给动静用户会以为按钮坏了。
    if (!state.hasValue) state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(taskRepositoryProvider).fetchActive(),
    );
  }

  /// 轮询一次。
  ///
  /// 【它和 [refresh] 的区别】这条路径**永远不会**把界面切到 loading，
  /// 也**永远不会**因为一次网络抖动把界面变成错误页 ——
  /// 每 5 秒闪一次骨架、或者等十分钟的过程中突然弹出一个错误框，
  /// 都是比「晚几秒看到新状态」糟糕得多的体验。
  /// 轮询失败就保持上一次的数据，等下一个周期再试。
  Future<void> pollOnce() async {
    final before = state.value ?? const <Task>[];

    final List<Task> after;
    try {
      after = await ref.read(taskRepositoryProvider).fetchActive();
    } on Object {
      // 见上：静默保持旧数据
      return;
    }

    state = AsyncData(after);
    await _announceFinished(before: before, after: after);
  }

  /// 找出「刚才还在跑、现在不在列表里」的任务，逐个通知用户。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【为什么不能只看新列表里有没有终态任务】
  /// 因为 `?status=active` 这个筛选**本来就不返回终态任务** ——
  /// 一个任务完成的那一刻，它就从这个列表里消失了。
  /// 所以判断「完成了」的唯一办法是**对比前后两次**：
  /// 上一轮有它、这一轮没有，那它一定是走到终态了。
  ///
  /// 【为什么要再打一次详情接口】因为列表里没有失败原因和最终状态，
  /// 而通知的正文要说清楚是「做好了」还是「失败了、积分已退回」——
  /// 这两句话对用户的意义完全不同（一个去作品里看，一个要确认钱回来了）。
  /// 一个任务只发生一次终态，这次额外的请求很便宜。
  /// ─────────────────────────────────────────────────────────
  Future<void> _announceFinished({
    required List<Task> before,
    required List<Task> after,
  }) async {
    if (before.isEmpty) return;

    final stillActive = after.map((t) => t.id).toSet();
    final finished = before.where((t) => !stillActive.contains(t.id)).toList();
    if (finished.isEmpty) return;

    final repo = ref.read(taskRepositoryProvider);
    final notifier = ref.read(taskNotifierProvider);
    for (final t in finished) {
      try {
        final done = await repo.fetchDetail(t.id);
        await notifier.notifyTaskFinished(done);
      } on Object {
        // 【为什么整段都要吞】见 TaskNotifier 的约定：一条通知发不出去，
        // 绝不能连累下面的「刷新已完成列表和作品」。
        // 用户真正想知道的是「我的东西好了吗」，不是「通知弹没弹」。
      }
    }

    // 任务进终态意味着三件事同时变了：已完成列表多一条、
    // 作品里可能多一个产物、余额（结算/退回）变了。
    _invalidateAfterTaskChange();
  }

  /// 取消任务（§12.1 `POST /tasks/{id}/cancel`）。
  ///
  /// 【为什么失败不在这里吞掉】因为取消**可能真的失败**
  /// （任务已经跑完了、已经取消了），而那一刻用户正盯着一个按钮等结果。
  /// 必须把错误抛给页面去说清楚，而不是让按钮转一下圈然后什么都没发生。
  ///
  /// 【退款政策不在这里判断】§7.4 分「排队中取消全额退」和
  /// 「已提交后取消不退」两种。这个判断要在**用户按下取消之前**就告诉过他
  /// （见任务详情页的确认弹窗），不能等取消完了再说。
  Future<void> cancel(String id) async {
    await ref.read(taskRepositoryProvider).cancel(id);
    await refresh();
    _invalidateAfterTaskChange();
  }

  /// 任务状态变化后，把受影响的缓存作废。
  void _invalidateAfterTaskChange() {
    ref.invalidate(doneTasksProvider);
    ref.invalidate(userAssetsProvider);
    // 余额：冻结、结算、退回都在改动它，而首页右上角和「我的」页都在显示它
    ref.invalidate(meProfileProvider);
  }
}

final activeTasksProvider =
    AsyncNotifierProvider<ActiveTasksNotifier, List<Task>>(
      ActiveTasksNotifier.new,
      // 见 `noAutoRetry` 的注释：默认的自动重试会让重试按钮变成假的
      retry: noAutoRetry,
    );

/// 已结束的任务（`GET /tasks?status=done`）
///
/// 【注意它包含失败、被拒、取消、过期的那些】不是只有成功的。
/// 这是刻意的（见 `TaskRepository.fetchDone` 的注释）：
/// 用户需要能看到「我那次失败了」，并且确认积分退回来了。
class DoneTasksNotifier extends AsyncNotifier<List<Task>> {
  @override
  Future<List<Task>> build() {
    final token = ref.watch(authTokenProvider);
    if (token == null) throw AppException.unauthorized();

    return ref.read(taskRepositoryProvider).fetchDone();
  }

  Future<void> refresh() async {
    if (!state.hasValue) state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(taskRepositoryProvider).fetchDone(),
    );
  }
}

final doneTasksProvider =
    AsyncNotifierProvider<DoneTasksNotifier, List<Task>>(
      DoneTasksNotifier.new,
      retry: noAutoRetry,
    );

/// 单个任务的详情（含排队位次、结算金额）
///
/// ─────────────────────────────────────────────────────────
/// 【为什么是 family 而不是「传一个 Task 对象进来」】
/// 因为 §8.4 说了任务状态不许存在 App 内存里。如果一个详情页是靠
/// `TaskDetailPage(task: someTask)` 打开的，那这个对象就是**打开那一刻的快照**：
/// 用户看着它的时候任务已经跑完了，页面还显示「生成中」，
/// 而且下拉刷新也没得刷（它手里只有那个死对象）。
///
/// 只传一个 id，页面就**必须**去服务端要 —— 这也正是我们想要的。
/// ─────────────────────────────────────────────────────────
///
/// 【为什么是 autoDispose】任务详情是「点进去才看」的东西。
/// 不 autoDispose 的话，用户逛过的每个任务都会在内存里留一份详情，
/// 逛上几十个就是几十份永远不会再看的对象。
class TaskDetailNotifier extends AsyncNotifier<Task> {
  TaskDetailNotifier(this.taskId);

  /// 要看的任务 id。**不是 Task 对象** —— 见类注释。
  final String taskId;

  @override
  Future<Task> build() {
    final token = ref.watch(authTokenProvider);
    if (token == null) throw AppException.unauthorized();

    return ref.read(taskRepositoryProvider).fetchDetail(taskId);
  }

  Future<void> refresh() async {
    if (!state.hasValue) state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(taskRepositoryProvider).fetchDetail(taskId),
    );
  }
}

final taskDetailProvider =
    AsyncNotifierProvider.autoDispose.family<TaskDetailNotifier, Task, String>(
      TaskDetailNotifier.new,
      retry: noAutoRetry,
    );

/// 轮询控制器 —— **任务状态刷新的唯一心跳**
///
/// ─────────────────────────────────────────────────────────
/// 【为什么它挂在 App 外壳上，而不是任务页自己身上】
///
/// §8.4 的要求是「用户可以离开那一屏，任务照样在跑」。
/// 如果定时器建在「进行中」那一页里，用户切到「我的」页去看了几眼积分，
/// 轮询就跟着页面一起没了 —— 十分钟后任务完成，通知不会响，
/// 回到作品页还要等下一次手动刷新才看得到。
///
/// 所以它挂在 [AppShell]（三个 Tab 的公共外壳）上：
/// 只要 App 在跑、还有人登录着，心跳就在。
///
/// 【为什么状态是 bool】
/// 这个值没有业务含义，它只是「现在在不在轮询」。
/// 留一个可观察的值是为了排查问题方便（和将来做「后台任务」指示器），
/// 不是为了给界面用 —— 界面上「有没有在进行中的任务」看 [activeTasksProvider]。
///
/// 【停止条件（§8.4 要求把这几条都写出来）】
///   1. 没有进行中的任务 → [syncWith] 收到空列表就停；
///   2. 登出 → token 变了，[activeTasksProvider] 会抛 401 进错误态，
///      外壳的监听看到「不是成功的数据」就不会再调度；
///   3. App 退到后台 → 外壳的生命周期回调里停（省电省流量）；
///   4. provider 被销毁 → `onDispose` 里取消定时器，**不留悬空 Timer**。
///
/// 【为什么 4 特别重要】一个没被取消的 `Timer` 会让 widget 测试在结束时报
/// 「A Timer is still pending even after the widget tree was disposed」——
/// 而且它还会在真机上让 App 无法被系统回收。
/// ─────────────────────────────────────────────────────────
class TaskPollingController extends Notifier<bool> {
  Timer? _timer;

  /// 已经轮询了多少次。退避策略按它算 —— 见 [TaskPollBackoff]。
  int _tick = 0;

  static const TaskPollBackoff _backoff = TaskPollBackoff();

  /// 间隔策略。测试可以直接读它来断言 5 秒 / 15 秒这件事。
  static TaskPollBackoff get backoff => _backoff;

  @override
  bool build() {
    ref.onDispose(() {
      // 只取消定时器，**不要在这里改 state** ——
      // 销毁过程中再写 state 会抛「Cannot use ref after dispose」。
      _timer?.cancel();
      _timer = null;
    });
    return false;
  }

  /// 现在在不在轮询。
  bool get isRunning => _timer != null;

  /// 跟着「有没有进行中的任务」同步心跳。
  ///
  /// 由 [AppShell] 用 `ref.listen(activeTasksProvider, ...)` 驱动。
  void syncWith(AsyncValue<List<Task>> active) {
    switch (active) {
      // 明确知道「一个进行中的任务都没有」→ 停
      case AsyncData(:final value) when value.isEmpty:
        _cancel();
      // 明确知道「有」→ 起（已经在跑就什么都不做）
      case AsyncData():
        _schedule();
      // loading / error：**不知道**有没有任务。
      // 【为什么这里不能停】一次网络抖动就把十分钟的心跳掐掉，
      // 那么任务完成时通知永远不会响 —— 这是最难查的那类 bug
      // （代码看起来没毛病，只是「偶尔不通知」）。不知道就不动它。
      default:
        break;
    }
  }

  /// 立刻停掉。App 退到后台时调用。
  void pause() => _cancel();

  void _schedule() {
    if (_timer != null) return;
    _timer = Timer(_backoff.delayFor(_tick), _onTick);
    if (!state) state = true;
  }

  Future<void> _onTick() async {
    // 先清空引用：下一次调度要靠 `_timer == null` 判断「现在没在跑」
    _timer = null;
    _tick++;

    await ref.read(activeTasksProvider.notifier).pollOnce();

    // 【为什么这里还要再判一次】因为 pollOnce 之后 `activeTasksProvider`
    // 可能已经变成空列表了（任务刚好做完）。这一轮不再调度 ——
    // 外壳那边的 ref.listen 也会收到同一个信号，两边是幂等的。
    final stillActive = ref.read(activeTasksProvider).value?.isNotEmpty ?? false;
    if (!stillActive) {
      state = false;
      return;
    }
    _schedule();
  }

  void _cancel() {
    _timer?.cancel();
    _timer = null;
    // 【为什么要重置计数】下一次「有任务了」应当重新从 5 秒起步 ——
    // 那多半是一个刚提交的新任务，前一分钟最可能出结果。
    _tick = 0;
    if (state) state = false;
  }
}

final taskPollingProvider =
    NotifierProvider<TaskPollingController, bool>(TaskPollingController.new);

/// 「任务完成」通知的出口。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么 Web 上是空实现】
/// flutter_local_notifications 确实有 Web 实现，但浏览器通知需要
/// 用户授权 + Service Worker，行为与移动端差别很大，而 v1 的 Web 端
/// 只用于**演示和验收**（§15）——演示时不弹系统通知反而更干净。
///
/// 【为什么用 `kIsWeb` 而不是条件导入】
/// 条件导入是为了绕开「某个平台上根本编译不过的包」。flutter_local_notifications
/// 22.x 自带 web 实现，**编译得过**，所以只需要在运行期选一个实现即可。
/// 条件导入会多出两个文件和一个「这两个文件必须保持同一套接口」的隐患，
/// 为了一个运行期分支不值得。
/// ─────────────────────────────────────────────────────────
final taskNotifierProvider = Provider<TaskNotifier>((ref) {
  if (kIsWeb) return const NoopTaskNotifier();
  return LocalTaskNotifier();
});
