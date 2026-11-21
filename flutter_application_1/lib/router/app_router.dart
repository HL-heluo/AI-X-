import 'package:flutter/material.dart';

import '../models/asset.dart';
import '../pages/auth/login_page.dart';
import '../pages/credits/credits_page.dart';
import '../pages/generate/image_gen_page.dart';
import '../pages/generate/image_result_page.dart';
import '../pages/generate/video_gen_page.dart';
import '../pages/generate/video_result_page.dart';
import '../pages/marketplace/marketplace_page.dart';
import '../pages/marketplace/verification_page.dart';
import '../pages/me/settings_page.dart';
import '../pages/task/task_detail_page.dart';
import '../widgets/app_background.dart';

/// ─────────────────────────────────────────────────────────
/// 路由的**唯一出处**
///
/// 【为什么不用 go_router】
/// ─────────────────────────────────────────────────────────
/// 三条理由，缺一条我都会换成它：
///
/// 1. **依赖面**。本地 pub 缓存里本来没有 go_router，而这个项目历经过
///    pub.dev 不稳定。11 屏的应用不值得为此多一个包。
/// 2. **用不上嵌套路由**。没有「Tabs 里再套 Tab」这种结构，
///    go_router 的 shell route 白拿。
/// 3. 公开核验的分享链接通过 [publicRoute] 解析。应用内任务页面仍用命名路由打开。
///
/// 迁移成本很低，因为路径常量已经集中在这一处、并且**真的被用上了**
/// （见 [route]）：换成 go_router 就是把这张表照抄一遍，
/// 页面一个都不用动。
/// ─────────────────────────────────────────────────────────
class AppRoutes {
  AppRoutes._();

  /// 登录 / 注册。
  ///
  /// 【为什么它不走 [route] 造出来】因为它是 `app.dart` 用 `home` 分发出来的，
  /// 不是 push 出来的 —— 用户没登录时它**就是**第一屏，栈里不该有东西在它下面。
  /// 这个常量更大的用处是当 `RouteSettings.name`，让日志里认得出「这是登录页」。
  static const String login = '/login';

  /// 积分：余额 + 流水。
  static const String credits = '/credits';

  /// 设置：退出登录 / 关于 / 版本。
  static const String settings = '/settings';
  static const String verify = '/verify';
  static const String marketplace = '/marketplace';

  static String verification(String evidenceId) =>
      '$verify/${Uri.encodeComponent(evidenceId)}';

  static Route<void>? publicRoute(RouteSettings settings) {
    final uri = Uri.tryParse(settings.name ?? '');
    if (uri == null ||
        !uri.path.startsWith('/') ||
        uri.pathSegments.isEmpty ||
        uri.pathSegments.first != 'verify' ||
        uri.pathSegments.length > 2) {
      return null;
    }
    return MaterialPageRoute<void>(
      settings: settings,
      builder: (_) => _frame(
        VerificationPage(
          evidenceId: uri.pathSegments.length == 2
              ? uri.pathSegments.last
              : null,
        ),
      ),
    );
  }

  /// 图片生成页（§13.2 的 `imageGen`）。
  static const String createImage = '/create/image';

  /// 视频生成页（§13.2 的 `videoGen`，v1 走图生视频）。
  static const String createVideo = '/create/video';

  /// 任务详情。**用 taskId 拼出来的**，不是传一个 Task 对象 ——
  /// 见 `taskDetailProvider` 的注释：传对象就等于把任务状态存进了 App 内存。
  static String taskDetail(String id) => '/task/$id';

  /// 图片结果页。
  static String imageResult(String id) => '/result/image/$id';

  /// 视频结果页。
  static String videoResult(String id) => '/result/video/$id';

  // 【为什么 [works] 没有路径常量】
  // 因为它是底部 Tab 之一，是 `home` 里的一个分支，**不是 push 出来的**。
  // 给它写一个 '/works' 会造出第二条件（既能 push 又能切 Tab），
  // 而两条路走进去的界面状态并不一样（push 进去的那一个没有底部 Tab 栏）。
  //
  // 【为什么 [credits] 和 [settings] 现在才出现，而不是 B4 时一起写好】
  // 因为一个没有页面可指向的路径常量是**纯装饰**：它不会报错、不会被引用、
  // 也没人会记得改它。更糟的是，真到实现那一屏时往往发现名字该改（比如
  // `createImageResult` 其实该叫 `taskResult`），于是又多一次改名。
  // 等到有页面要指向它的那一刻再写，那时名字是**被用途逼出来的** ——
  // 这两个就是「我的」页真的需要跳过去时，才落下来的。

  /// 造一个带名字的页面路由。
  ///
  /// 【为什么每页都要塞 name】因为不塞的话，Flutter 的路由栈里全是
  /// `null` 名字 —— 排查「用户是怎么走到这一页的」时，栈打出来是一串空白。
  /// 顺带，这也正是将来迁 go_router 时能一一对应上的那层。
  static Route<T> route<T>(
    String name,
    Widget Function(BuildContext context) builder,
  ) {
    return MaterialPageRoute<T>(
      settings: RouteSettings(name: name),
      builder: (context) => _frame(builder(context)),
    );
  }

  static Widget _frame(Widget page) => AppBackground(
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 880),
        child: SizedBox.expand(child: page),
      ),
    ),
  );

  static Route<T> loginRoute<T>() => route<T>(login, (_) => const LoginPage());

  static Route<T> creditsRoute<T>() =>
      route<T>(credits, (_) => const CreditsPage());

  static Route<T> settingsRoute<T>() =>
      route<T>(settings, (_) => const SettingsPage());
  static Route<void> workRoute(String assetId) => route<void>(
    '$marketplace/works/$assetId',
    (_) => MarketWorkPage(assetId: assetId),
  );

  static Route<T> taskDetailRoute<T>(String taskId) =>
      route<T>(taskDetail(taskId), (_) => TaskDetailPage(taskId: taskId));

  static Route<T> imageGenRoute<T>({String? prompt}) =>
      route<T>(createImage, (_) => ImageGenPage(initialPrompt: prompt));

  static Route<T> videoGenRoute<T>({String? sourceAssetId, String? prompt}) =>
      route<T>(
        createVideo,
        (_) =>
            VideoGenPage(sourceAssetId: sourceAssetId, initialPrompt: prompt),
      );

  static Route<T> imageResultRoute<T>(String taskId) =>
      route<T>(imageResult(taskId), (_) => ImageResultPage(taskId: taskId));

  static Route<T> videoResultRoute<T>(String taskId) =>
      route<T>(videoResult(taskId), (_) => VideoResultPage(taskId: taskId));

  /// 打开**一件作品**（`Asset`）要去哪一页。
  ///
  /// 【为什么这件事归路由层管，而不是各页面自己判】
  /// 因为「点一件作品该看到什么」是一个**全局一致**的决定：
  /// 用户点开一件作品，想看的是作品本身（大图、播放），不是任务详情
  /// （排队历史、结算明细 —— 那些从结果页里进得去，反过来不顺）。
  /// 这个判断原来写在 `WorksPage._openAsset` 里，于是首页的「最近作品」
  /// 要再抄一遍 —— 抄一遍就等于埋一次「两处慢慢变得不一样」。
  ///
  /// 【返回 null 的两种情况】`task_id` 为空的资产是**用户自己上传的参考图**
  /// （见 `Asset` 模型注释），它不是「某次生成的结果」，没有结果页可去。
  /// 调用方拿到 null 时应当什么都不做 —— 「点了没反应」比跳进一个空白页好。
  static Route<void>? assetResultRoute(Asset asset) {
    final taskId = asset.taskId;
    if (taskId == null) return null;
    return asset.isVideo
        ? videoResultRoute<void>(taskId)
        : imageResultRoute<void>(taskId);
  }
}
