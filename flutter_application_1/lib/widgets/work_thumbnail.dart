import 'package:flutter/material.dart';

import '../models/asset.dart';
import '../theme/app_theme.dart';
import 'ai_generated_badge.dart';

/// 一张作品缩略图
///
/// ─────────────────────────────────────────────────────────
/// 【为什么加载中和加载失败都要画一个「像样」的东西】
///
/// 作品网格一屏要摆 6~9 张图，任何一张的加载状态都会被用户看见。
/// 三种写法都不能接受：
///   * 转圈 —— 九个转圈同时转，页面像卡死了（而且它会让 widget 测试超时，
///     见 `async_section.dart` 里那段）；
///   * 留白 —— 用户以为这一格是空的、作品丢了；
///   * 让 `Image.network` 自己报错 —— 屏幕上会出现红色的异常方块。
///
/// 所以这里统一用一个**静态的占位块**：和格子同尺寸、同圆角、
/// 带一个淡淡的图标。加载中和加载失败用同一个样子 ——
/// 因为对用户来说这两件事的差别是「再等等」和「刷新一下」，
/// 而两者他都会做，不值得在这么小的格子里区分。
///
/// 【调用方要给确定的宽高】这个组件会铺满外面给的约束
/// （用 `AspectRatio` 或 `SizedBox` 包一下）。放进无界高度的地方
/// （比如没给定高的 `Column`）会报错 —— 这是 Flutter 的规矩，不是这里的怪癖。
/// ─────────────────────────────────────────────────────────
class WorkThumbnail extends StatelessWidget {
  const WorkThumbnail({
    super.key,
    required this.asset,
    this.coverUrl,
    this.showBadge,
    this.compact = false,
    this.radius = AppRadius.lg,
    this.showPlayMark = true,
  });

  final Asset asset;

  /// 视频的封面图地址。
  ///
  /// 【为什么不让 [asset] 自己去拿】因为封面是**另一个资产**
  /// （§11.2 里 `thumbnail` 和 `video` 是两行独立记录）。
  /// 把它们配成一对是上层的事（按 taskId 配对），这个组件只负责画。
  final String? coverUrl;

  /// 是否压「AI 生成」标识。**不传就由 `asset.isAiGenerated` 决定。**
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【为什么默认不是恒 true —— 以及这里曾经是错的】
  ///
  /// 这个组件出现的地方是**混装**的：作品网格与首页「最近作品」里既有
  /// AI 产物，也有用户**自己上传的参考图**（`assets.is_ai_generated = false`）。
  /// 恒打标等于把人的照片标成 AI —— 与「AI 产物必须有标」方向相反，
  /// 但同样落在《标识办法》的射程里，而且是更难解释的那一侧。
  ///
  /// 这个缺陷实测出现过：作品页「已完成」里上传的那一格戴着「AI 生成」。
  /// 根因是 `Asset.isAiGenerated` 这个字段**从来没有任何 widget 读过** ——
  /// 它是为这件事建的（见 `models/asset.dart` 那段说明），mock 也一直
  /// 如实填 `false`，**只有画这一格的地方没接线**。
  ///
  /// 【为什么缺省是 `null` 而不是 `bool ... = true`】
  /// 因为 `= true` 分不清「调用方明确要标」和「调用方没传」，
  /// 而这两件事在这里的正确答案不一样。`null` 把两种意图分开：
  /// 没传 → 跟着资产走；传了 → 听调用方的（[AiGeneratedFrame] 那句
  /// 「宁可多打标，不能少打」仍然可以由调用方显式保证）。
  ///
  /// ⚠️ **缺省落到的是安全的那一侧**：`Asset.fromJson` 对缺字段的
  /// 默认值是 `true`（见 `models/asset.dart`，有测试钉着），
  /// 所以「解析不出来」时打标，不是不打。
  /// ─────────────────────────────────────────────────────────
  final bool? showBadge;

  final bool compact;
  final double radius;

  /// 是否盖播放按钮（视频专用）。
  final bool showPlayMark;

  @override
  Widget build(BuildContext context) {
    // 视频用封面图，图片用它自己
    final url = asset.isVideo ? coverUrl : asset.publicUrl;

    return AiGeneratedFrame(
      show: showBadge ?? asset.isAiGenerated,
      compact: compact,
      radius: radius,
      child: Stack(
        children: [
          // 【为什么画面是唯一的非定位子组件】Stack 的尺寸由它决定。
          // 全部子组件都定位的话，Stack 会塌成 0 或者撑满外层约束 ——
          // 前者让播放标记无处可放，后者在无界约束下直接报错。
          _Picture(url: url, compact: compact),
          if (asset.isVideo && showPlayMark)
            const Positioned.fill(child: _PlayMark()),
        ],
      ),
    );
  }
}

/// 图片本体 + 占位
class _Picture extends StatelessWidget {
  const _Picture({required this.url, required this.compact});

  final String? url;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final placeholder = _Placeholder(compact: compact);

    if (url == null || url!.isEmpty) return placeholder;

    return Image.network(
      url!,
      // cover：网格的高度是按比例算好的，图片按比例裁切填满，
      // 而不是被拉变形
      fit: BoxFit.cover,
      // 铺满外层给的约束
      width: double.infinity,
      height: double.infinity,
      // 加载中：静态占位，**不是转圈**
      loadingBuilder: (context, child, progress) =>
          progress == null ? child : placeholder,
      // 加载失败：同一个占位。网络会失败是常态（断网、图被删了、
      // Mock 阶段的地址本来就不存在），这里必须接住 ——
      // 不接住的话 Flutter 会把它报成一条未捕获异常，
      // widget 测试里就是一片红。
      errorBuilder: (context, error, stack) => placeholder,
    );
  }
}

/// 静态占位块
class _Placeholder extends StatelessWidget {
  const _Placeholder({required this.compact});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Container(
      // 没有子组件但有 alignment 时，Container 会撑满外层给的约束
      alignment: Alignment.center,
      decoration: const BoxDecoration(color: AppColors.sunken),
      child: Icon(
        Icons.image_outlined,
        size: compact ? 20 : 26,
        // 比 taupe 更淡：它是「这里什么都没有」的提示，不该抢眼
        color: AppColors.taupe.withValues(alpha: 0.5),
      ),
    );
  }
}

/// 视频格子上那个圆形的播放标记
class _PlayMark extends StatelessWidget {
  const _PlayMark();

  @override
  Widget build(BuildContext context) {
    // Positioned.fill + Center：不管格子多大，标记都在正中
    return const Center(
      child: SizedBox(
        width: 34,
        height: 34,
        child: DecoratedBox(
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: Color(0x66000000),
          ),
          child: Icon(
            Icons.play_arrow_rounded,
            size: 22,
            color: Colors.white,
          ),
        ),
      ),
    );
  }
}
