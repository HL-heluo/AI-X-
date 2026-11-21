import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 「AI 生成」标识 —— **合规件，不是装饰**
///
/// ─────────────────────────────────────────────────────────
/// 【为什么它必须存在，而且必须看得见】
///
/// 《人工智能生成合成内容标识办法》2025-09-01 起施行（工程文档 §10.1）：
/// 生成的图片、视频**必须带有可见的标识**。这是法律义务，不是产品选择 ——
/// 少一个标识，平台是违法的，和「设计上好不好看」无关。
///
/// 【那为什么还要单独做一个组件，而不是每处写一个 Text】
/// 因为「可见」是有标准的，而这个标准不该由每个页面自己理解：
///   * 必须压在图片/视频**上面**（不能放在页面底部的说明文字里，
///     用户滑到一半截图，标识必须在画面上）；
///   * 必须在任何画面上都能读（深色图、浅色图、花的图都得清楚）；
///   * 必须写明「AI 生成」四个字（写「AI」不够 —— 那是产品名还是性质？
///     法规要的是性质）。
/// 把它固定成一个组件，这三点就只有一份实现，改也只用改一次。
///
/// 【为什么用深底白字，而不是设计系统里的浅色毛玻璃】
/// 因为毛玻璃效果依赖它底下是什么。压在雪景上和压在夜景上，
/// 可读性差得远 —— 一个可能看不清的合规标识等于没有。
/// 半透明黑底 + 白字是在任何底图上都成立的组合。
/// 这里刻意不取 `AppGlass.*`：那些是**设计风格**的 token，
/// 而这个组件的首要目标是**在最坏情况下也能读**，不是好看。
/// ─────────────────────────────────────────────────────────
class AiGeneratedBadge extends StatelessWidget {
  const AiGeneratedBadge({
    super.key,
    this.compact = false,
    this.margin = const EdgeInsets.all(6),
  });

  /// 紧凑样式（小网格里的缩略图上用）。
  ///
  /// 【为什么不是简单地缩放】网格里一个格子只有 100 多像素宽，
  /// 同样的字号会占掉快一半宽度。紧凑档单独调字号和内边距，
  /// 而不是外面套一个 `Transform.scale` —— 缩放会让字发虚。
  final bool compact;

  /// 距容器边缘的距离。默认 6，网格里可以调小。
  final EdgeInsets margin;

  /// 标识文案。**不要改这四个字** —— 见类注释。
  static const String label = 'AI 生成';

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: margin,
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 4 : 6,
        vertical: compact ? 1.5 : 3,
      ),
      decoration: BoxDecoration(
        // 【为什么是 0x8A 而不是纯黑】纯黑太抢戏，会让整张作品看起来像
        // 被打了个补丁。这个透明度刚好：亮底上能看出是一块深色标签，
        // 暗底上又不会糊成一片。
        color: const Color(0x8A000000),
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: compact ? 8.5 : 10,
          fontWeight: FontWeight.w600,
          color: Colors.white,
          // 字距拉开一点，小字号下更清楚
          letterSpacing: 0.2,
        ),
      ),
    );
  }
}

/// 把「AI 生成」标识压在一个子组件（图片 / 视频）的左上角。
///
/// 【为什么是左上角】右上角在结果页要留给「关闭 / 更多」这类操作，
/// 右下角留给时长和分辨率。左上角是唯一不会被别的东西占用的位置。
///
/// 【为什么要包一层而不是让调用方自己 Stack】因为「标识必须在画面上」
/// 这条规则如果靠调用方自觉，迟早有一处忘了 —— 忘的那一处就是违规。
/// 包起来之后，只要用了 [AiGeneratedFrame]，标识就必然在。
class AiGeneratedFrame extends StatelessWidget {
  const AiGeneratedFrame({
    super.key,
    required this.child,
    this.compact = false,
    this.show = true,
    this.radius = AppRadius.lg,
  });

  /// 画面本体（图片、视频播放器、缩略图……）。
  final Widget child;

  /// 是否显示标识。
  ///
  /// 【为什么允许关掉】因为同一个画面里可能需要连打两个标
  /// （网格的格子已经有标了，点开的结果页不该再叠一个）。
  /// 但**默认是 true** —— 漏传参数时宁可多打标，不能少打（§10.1）。
  final bool show;

  final bool compact;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: Stack(
        children: [
          // 【为什么 child 不是 Positioned.fill】
          // 因为 Stack 的尺寸是**由非定位子组件决定的**。全部子组件都定位时，
          // Stack 会塌成 0 或者撑满外层约束 —— 前者让标识无处可压，
          // 后者在无界高度的地方（比如放进 ListView）直接报错。
          // 让画面当那个「定尺寸的子组件」，标识再相对它定位，
          // 这样外面的约束是什么样都成立。
          child,
          if (show)
            Positioned(
              left: 0,
              top: 0,
              child: AiGeneratedBadge(
                compact: compact,
                margin: EdgeInsets.all(compact ? 4 : 8),
              ),
            ),
        ],
      ),
    );
  }
}
