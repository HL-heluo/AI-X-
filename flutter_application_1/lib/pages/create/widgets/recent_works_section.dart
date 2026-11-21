import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/asset.dart';
import '../../../providers/asset_providers.dart';
import '../../../router/app_router.dart';
import '../../../theme/app_theme.dart';
import '../../../widgets/section_title.dart';
import '../../../widgets/work_grid.dart';

/// 「最近作品」区
///
/// 【前端类比】对应原型 `home()` 里的 `.works-grid`：两列，卡片高矮交错。
///
/// 【为什么要手写两列，而不是用 GridView】
/// 原型是个 CSS grid，卡片有 `.tall`（3/4）和 `.short`（1/1）两种比例，
/// 同一行里两个卡片高度并不相等 —— GridView 的每行高度是统一的，做不到。
/// 所以这里用「两个 Column 并排」的方式，各自控制高度。
/// 这套排版已经抽成了 [WorkGrid]（作品页用的是同一个），这里有变化才怪。
///
/// ─────────────────────────────────────────────────────────
/// 【B6：从「4 个空色块」换成真数据】
///
/// 数据源是 `userAssetsProvider` —— **和作品页同一个 provider**，
/// 不是另开一个「首页作品」。理由：
///
/// 1. 它是一份数据的两处展示，两份 provider 就必然出现
///    「在作品页删了一张图，回到首页它还在」这种不一致；
/// 2. 首页这边**不翻页**，只取前几条（见 [_maxItems]），
///    而分页状态（已经加载到第几页）只有一份才不会错乱。
///
/// 【为什么只取前 4 条、而不是把全部分页拉完】首页是个「一眼看过去」的地方。
/// 用户想看全部，点「全部 ›」去作品页 —— 那里才有翻页。
/// 在首页把几百张图都拉下来，是最典型的「打开了 App 就在烧流量」。
///
/// 【为什么它自己不 watch token / 不发请求】`userAssetsProvider` 的
/// `build()` 里已经 watch 过了（见那边的注释）。这里再判一次没有意义，
/// 而且会让「登录态」这件事有两个出处。
/// ─────────────────────────────────────────────────────────
class RecentWorksSection extends ConsumerWidget {
  const RecentWorksSection({super.key, this.onSeeAll});

  /// 点标题右边的「全部 ›」。切到作品页的「已完成」分段 —— 具体见
  /// `CreatePage` 里的调用点（为什么连分段一起切，写在那儿）。
  final VoidCallback? onSeeAll;

  /// 最多摆几件。两列各两格，正好铺满一屏能看见的范围。
  static const int _maxItems = 4;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final assets = ref.watch(userAssetsProvider);
    final state = assets.value;

    // 【为什么用 works 而不是 assets】`assets` 里还混着视频的**封面图**
    // （它是独立的一条记录，见 §11.2）。不过滤的话，一个视频会在网格里
    // 占两格 —— 一格视频、一格它自己的封面图。
    final works = state?.works ?? const <Asset>[];
    final shown = works.take(_maxItems).toList(growable: false);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 【为什么要包一层 GestureDetector，而不是给 SectionTitle 加回调】
        // `section_title.dart` 是冻结的（§3.3.1），而且它的注释里明确写着
        // 「这一轮不做点击，所以它只是个字符串，不是按钮」。
        // 改它就要动一个全项目公用的组件，风险远大于收益 ——
        // 这里就地包一层，代价是「可点区域只有这一行的高度」，
        // 而那一行本来就正是用户会去点的位置。
        GestureDetector(
          // 【为什么 key 挂在 GestureDetector 上而不是 SectionTitle 上】
          // 因为要点的就是这一层（SectionTitle 自己没有点击）。
          // 测试里点它比点「全部 ›」那几个字稳 —— 文字可能会改。
          key: const Key('home.seeAll'),
          // 这一层只负责「能点」，不负责「看起来能点」：
          // 「全部 ›」这几个字本身就是那个提示。
          onTap: onSeeAll,
          behavior: HitTestBehavior.opaque,
          child: const SectionTitle(title: '最近作品', action: '全部 ›'),
        ),
        // ── 三种状态 ──────────────────────────────────────
        if (state == null)
          // 【为什么 loading 和 error 都是骨架】拿不到数据时，
          // 首页这一块不该变成一个红色错误框 —— 它只是页面的第五块内容，
          // 而错误处理的主战场是作品页（那里有「重试」按钮和下拉刷新）。
          // 这里保持和「正在加载」一样的形状，用户滑过去不会觉得哪里坏了。
          const _WorksSkeleton()
        else if (shown.isEmpty)
          const _EmptyWorks()
        else
          WorkGrid(
            assets: shown,
            coverUrlOf: state.coverUrlOf,
            onTap: (asset) => _openAsset(context, asset),
          ),
      ],
    );
  }

  /// 点开一件作品。
  ///
  /// 【为什么调 `AppRoutes.assetResultRoute` 而不是自己判 if】
  /// 因为作品页点同一件东西时也要做这个判断。两处各写一份，
  /// 迟早会出现「首页点进去是视频详情、作品页点进去是图片详情」。
  static void _openAsset(BuildContext context, Asset asset) {
    final route = AppRoutes.assetResultRoute(asset);
    if (route == null) return;
    Navigator.of(context).push<void>(route);
  }
}

/// 空状态
///
/// 【为什么不复用作品页那个 `_Empty`】那是私有的，而且尺寸按整页设计
/// （上下各 54 的留白）。首页这一块只需要一小块安静的区域 ——
/// 它上面还有输入框和「创作场景」，把这里撑高会把主线的入口挤出屏幕。
class _EmptyWorks extends StatelessWidget {
  const _EmptyWorks();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 20),
      decoration: BoxDecoration(
        color: AppGlass.normal,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppGlass.border, width: 1),
      ),
      child: const Column(
        children: [
          Icon(Icons.image_outlined, size: 26, color: AppColors.taupe),
          SizedBox(height: 10),
          Text(
            '还没有作品',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppColors.charcoal,
            ),
          ),
          SizedBox(height: 4),
          Text(
            // 【为什么指回上面而不是说「去作品页」】用户此刻的处境是
            // 「刚装好 App / 一件都还没做」，正确的下一步就是**上面那个输入框**。
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 11.5, height: 1.6, color: AppColors.taupe),
            '在上面写一句描述，生成的图片和视频会出现在这里',
          ),
        ],
      ),
    );
  }
}

/// 加载骨架：和真实网格同形的几个灰块
///
/// 【为什么不能用转圈】见 `async_section.dart`：一个永不停止的动画
/// 会让 widget 测试的 `pumpAndSettle()` 直接超时。
class _WorksSkeleton extends StatelessWidget {
  const _WorksSkeleton();

  /// 两列之间的间距（CSS: .works-grid { gap: 10px }）
  static const double _gap = 10;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        // 先算出单列宽度，再按比例反推高度 ——
        // 比直接写固定像素更稳，换屏幕尺寸也不会错位。
        final colWidth = (constraints.maxWidth - _gap) / 2;

        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                children: [
                  _block(colWidth * 4 / 3), // 竖的一格（原型 .tall 是 3/4）
                  const SizedBox(height: _gap),
                  _block(colWidth),
                ],
              ),
            ),
            const SizedBox(width: _gap),
            Expanded(
              child: Column(
                children: [
                  _block(colWidth),
                  const SizedBox(height: _gap),
                  _block(colWidth * 4 / 3),
                ],
              ),
            ),
          ],
        );
      },
    );
  }

  /// 一块灰底。用 `sunken`（4% 黑）而不是原型的渐变 ——
  /// 骨架不该带颜色，否则真数据回来时会「变色」。
  static Widget _block(double height) {
    return Container(
      height: height,
      decoration: BoxDecoration(
        color: AppColors.sunken,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
    );
  }
}
