import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../../models/task.dart';
import '../constants/task_status.dart';
import 'task_notifier.dart';

/// 用系统本地通知实现 [TaskNotifier]
///
/// ─────────────────────────────────────────────────────────
/// 【为什么是「本地通知」而不是推送】
/// 因为 §8.4 要的是「任务完成时告诉用户」，而**知道任务完成的人是我们自己的
/// 轮询循环**（App 在前台或刚回到前台时拉的）。既然消息本来就到了手上，
/// 再绕一圈 FCM / APNs 没有任何好处 —— 还要多一套推送证书和 token 管理。
///
/// 代价也要说清楚：App 被系统彻底冻结（用户划掉了它）时轮询不再跑，
/// 这条通知就发不出来。**接真后端时正确的做法是服务端在任务完成时发一条
/// 推送**，那时这个类会退化成「App 在前台时的即时提醒」。
/// 现在这样做的理由是：v1 是内测 + 侧载，没有推送证书，而本地通知
/// 能把「十分钟的等待」这条体验真正闭环。
/// ─────────────────────────────────────────────────────────
///
/// 【为什么所有方法都吞异常】
/// 见 [TaskNotifier.notifyTaskFinished] 的约定。这里再补一条具体原因：
/// 通知在真机上失败的方式非常多 —— 用户拒绝了权限、Android 13 以下没有
/// 通知渠道概念、iOS 需要在前台显式申请、系统把渠道关了。
/// 这些**都不是我们的 bug**，更不该让任务状态更新失败。
class LocalTaskNotifier implements TaskNotifier {
  LocalTaskNotifier({FlutterLocalNotificationsPlugin? plugin})
      : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _plugin;

  /// 初始化只做一次。第一次要用通知时才初始化 ——
  /// 冷启动时多一次插件调用没有任何好处。
  Future<void>? _ready;

  /// 通知 id。同 id 的通知会覆盖上一条 ——
  /// 我们按任务 id 取模分配，免得一个用户跑了很多任务后把通知栏塞满。
  static const int _idSpace = 1 << 20;

  @override
  Future<void> notifyTaskFinished(Task task) async {
    try {
      await (_ready ??= _init());
      final details = _detailsFor(task);

      await _plugin.show(
        id: task.id.hashCode % _idSpace,
        title: _titleFor(task),
        // 【为什么把提示词带进正文】用户可能同时跑了图片和视频，
        // 只写「生成完成」他得点进去才知道是哪一个。提示词是他自己写的，
        // 一眼就能认出来。截断是因为通知栏只有一两行的位置。
        body: _bodyFor(task),
        notificationDetails: details,
        // 【payload 是留给未来的深链的】现在没有解析它的地方，
        // 但先带上 task id —— 等哪天做了通知点击跳转任务详情（见
        // app_router.dart 里那条迁移触发条件），这条数据已经在手上了。
        payload: task.id,
      );
    } on Object {
      // 见类注释：通知失败绝不能影响任务状态本身
    }
  }

  Future<void> _init() async {
    await _plugin.initialize(
      settings: const InitializationSettings(
        // 【为什么用启动图标当通知图标】Android 的通知小图标必须是
        // **纯白色的单色图**，用彩色的 launcher 图标会显示成一个白方块。
        // 但 v1 没有单独做一张通知图标（那是美术的活），
        // 而 @mipmap/ic_launcher 至少能保证「有东西显示、不崩」。
        // 等有设计师给图了，换掉这一个常量即可。
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(
          // 【为什么要在这里就把权限要了】iOS 的通知权限只能在
          // 「有通知要发」的时机之外申请，且系统只弹一次。
          // 用 requestAlertPermission 默认值 true 在初始化的同时申请，
          // 比等到任务完成那一刻再弹窗合理（那时用户已经离开这一屏了）。
          requestAlertPermission: true,
          requestBadgePermission: false,
          requestSoundPermission: true,
        ),
      ),
    );

    // Android 13（API 33）起，通知权限是**运行时权限**，
    // 要在 AndroidManifest 里声明 POST_NOTIFICATIONS 并主动申请，
    // 否则通知会被系统直接丢掉，而且一点提示都没有。
    // 用户拒绝也没关系 —— 上面那句 catch 会兜住后续的失败。
    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
  }

  NotificationDetails _detailsFor(Task task) {
    // 只有 succeeded 走「好事」那条渠道，其余（失败/被拒/取消/过期）都要
    // 让用户注意到 —— 它们多半意味着一笔冻结需要解释。
    final failed = task.status != TaskStatus.succeeded;

    return NotificationDetails(
      android: AndroidNotificationDetails(
        // 【渠道为什么要分成功/失败两条】用户可以在系统设置里按渠道关掉通知。
        // 把两类分到不同渠道，他就能「失败的留着，成功的别烦我」——
        // 合成一个渠道的话，他只能全关。
        failed ? 'task_failed' : 'task_succeeded',
        failed ? '任务未完成' : '任务完成',
        channelDescription: failed
            ? '生成失败或被拒绝，积分已退回'
            : '你提交的图片或视频已经生成好了',
        // 成功用 default，失败用 high（失败往往意味着钱的事，值得更显眼）
        importance: failed ? Importance.high : Importance.defaultImportance,
        priority: failed ? Priority.high : Priority.defaultPriority,
      ),
      iOS: const DarwinNotificationDetails(),
    );
  }

  String _titleFor(Task task) {
    return switch (task.status) {
      TaskStatus.succeeded => '${task.kind.label}生成完成',
      TaskStatus.rejected => '${task.kind.label}未通过审核',
      TaskStatus.failed => '${task.kind.label}生成失败',
      TaskStatus.canceled => '${task.kind.label}已取消',
      TaskStatus.expired => '${task.kind.label}已过期',
      // 理论上到不了这里：只有终态才会触发通知（见 TaskPollingController）。
      // 真到了也不能编一个说法，就按「有结果了」说。
      TaskStatus.pending ||
      TaskStatus.queued ||
      TaskStatus.submitted =>
        '${task.kind.label}任务有更新',
    };
  }

  String _bodyFor(Task task) {
    final prompt = _shorten(task.prompt);

    return switch (task.status) {
      // 【为什么成功时要说「去作品里看」而不是「点击查看」】
      // 因为 v1 还没有通知点击跳转（见 payload 那段注释）。
      // 写「点击查看」而点了没反应，比不写更伤。
      TaskStatus.succeeded => '「$prompt」已完成，去「作品」里看看',
      TaskStatus.rejected => '「$prompt」未通过审核，积分已退回',
      TaskStatus.failed => '「$prompt」生成失败，积分已退回',
      TaskStatus.canceled => '「$prompt」已取消',
      TaskStatus.expired => '「$prompt」已过期，积分已退回',
      TaskStatus.pending ||
      TaskStatus.queued ||
      TaskStatus.submitted =>
        '「$prompt」状态有更新',
    };
  }

  /// 通知栏只有一两行的位置。这里按**字符数**截断即可 ——
  /// 中英文混排的精确宽度要靠排版引擎算，为一条通知不值得。
  static String _shorten(String text, {int max = 24}) {
    final trimmed = text.trim().replaceAll(RegExp(r'\s+'), ' ');
    if (trimmed.length <= max) return trimmed;
    return '${trimmed.substring(0, max)}…';
  }
}
