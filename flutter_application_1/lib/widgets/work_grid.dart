import 'package:flutter/material.dart';

import '../models/asset.dart';
import 'work_thumbnail.dart';

/// 响应式作品网格，每格按作品比例排高度。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么按列排列，而不是用 GridView】
///
/// 因为 `GridView` 的**每一行高度是统一的**，而我们的作品有横有竖：
/// 图片是 1:1，视频是 16:9。塞进固定行高的网格里只有两种结果 ——
/// 要么把竖图裁成方的（用户构图被切掉一半），
/// 要么把横图上下留一大片白（看起来像加载失败）。
///
/// 原型 `home()` 里的 `.works-grid` 就是 CSS grid 做的瀑布流，
/// 这里用多个 Column 并排还原它：每列自己决定每格多高，
/// 于是同一行里左右两格高度可以不一样。
///
/// 【为什么按顺序分列，而不是累计高度分列】
/// 累计高度只在「先把所有高度算出来」时才做得到，而那是**离屏计算**：
/// 一次要算几百张图的布局，滑动时会卡。顺序分列是流式的 ——
/// 看一条摆一条，代价是两列总高可能差一点点。
/// 对一个作品列表来说，这个差别小到看不出来，而流畅度是能感觉到的。
/// ─────────────────────────────────────────────────────────
///
/// 【调用方要给它确定的宽度】它内部用 `LayoutBuilder` 算列宽，
/// 所以必须放在有横向约束的地方（ListView 里的普通子组件即可）。
class WorkGrid extends StatelessWidget {
  const WorkGrid({
    super.key,
    required this.assets,
    required this.coverUrlOf,
    required this.onTap,
    this.gap = 10,
  });

  /// 要摆的作品。**应当已经过滤掉 `thumbnail`**
  /// （见 `UserAssetsState.works`）。
  final List<Asset> assets;

  /// 取某个视频的封面地址。由上层传入 —— 因为「哪张封面配哪个视频」
  /// 是列表整体的知识（见 `UserAssetsState.coverUrlOf`）。
  final String? Function(Asset asset) coverUrlOf;

  final void Function(Asset asset) onTap;

  /// 列间距和每格之间的纵向间距。
  final double gap;

  /// 单格高度 = 列宽 ÷ 宽高比。把比例夹在这个区间里。
  ///
  /// 【为什么必须夹】宽高比来自服务端的 `width` / `height`，
  /// 而那是**不可信输入**：一个 9:32 的长图会让这一格有三屏那么高，
  /// 一次滑动全被它吃掉；一个 5:1 的横幅又会让那一格小得点不中。
  /// 夹住之后最坏情况只是裁掉一点，但版面始终可用。
  static const double _minRatio = 0.6;
  static const double _maxRatio = 1.8;

  /// 拿不到宽高时的默认比例。
  ///
  /// 【为什么是 3/4 而不是 1】见 `Asset.aspectRatio` 的注释：
  /// 随便返回 1.0 会把竖屏视频排成方的。这个默认值宁可偏竖一点。
  static const double _fallbackRatio = 3 / 4;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        // 先算出单列宽度，再按比例反推每格高度 ——
        // 比写固定像素稳，换屏幕尺寸也不会错位。
        final columnCount = (constraints.maxWidth ~/ 240).clamp(2, 4);
        final colWidth =
            (constraints.maxWidth - (columnCount - 1) * gap) / columnCount;

        final columns = List.generate(columnCount, (_) => <Asset>[]);
        for (var i = 0; i < assets.length; i++) {
          columns[i % columnCount].add(assets[i]);
        }

        return Row(
          // 【为什么要 start】默认是 stretch，两列会被拉成一样高 ——
          // 那正好抵消了瀑布流的意义（矮的那列下面会多出一片空白）。
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < columnCount; i++) ...[
              if (i > 0) SizedBox(width: gap),
              Expanded(child: _column(columns[i], colWidth)),
            ],
          ],
        );
      },
    );
  }

  Widget _column(List<Asset> items, double colWidth) {
    return Column(
      children: [
        for (var i = 0; i < items.length; i++) ...[
          if (i > 0) SizedBox(height: gap),
          _tile(items[i], colWidth),
        ],
      ],
    );
  }

  Widget _tile(Asset asset, double colWidth) {
    return SizedBox(
      width: colWidth,
      height: colWidth / _ratioOf(asset),
      child: GestureDetector(
        // 【为什么是 opaque】缩略图加载失败时它是一个没有子内容的占位块，
        // 默认的 deferToChild 会让「点空白处」失效 ——
        // 用户点的是整张卡，感知不到哪里是图片哪里是空白。
        behavior: HitTestBehavior.opaque,
        onTap: () => onTap(asset),
        child: WorkThumbnail(asset: asset, coverUrl: coverUrlOf(asset)),
      ),
    );
  }

  /// 单格的宽高比（宽/高），已夹在可用区间内。
  static double _ratioOf(Asset asset) {
    final raw = asset.aspectRatio ?? _fallbackRatio;
    return raw.clamp(_minRatio, _maxRatio);
  }
}
