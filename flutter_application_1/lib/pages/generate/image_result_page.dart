import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/asset.dart';
import '../../models/task.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ai_generated_badge.dart';
import 'widgets/gen_parts.dart';
import 'widgets/result_body.dart';

/// 图片结果页
///
/// ─────────────────────────────────────────────────────────
/// 【为什么它和「任务详情」是两个页面】
///
/// 因为用户从作品里点开一件作品时，想看的是**作品本身** ——
/// 大图、构图、要不要拿去做视频。他不想看排队历史、冻结了多少积分、
/// 什么时候入队的。
///
/// 但那些信息**也不能没有**（积分出问题时他要能对账），
/// 所以这一页底部照样带一份提示词和结算说明，
/// 而且从结果页跳去任务详情只是一次点击。
///
/// 【这一页也是「图片 → 视频」这条主线的中转站】
/// 「做成视频」是这一页最主要的动作 —— 见 §14.4：图片是入口，视频是卖点，
/// 中间那一步「选一张图」不是多余的，它让用户先确认素材满意了再花钱生成视频。
/// ─────────────────────────────────────────────────────────
class ImageResultPage extends ConsumerWidget {
  const ImageResultPage({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: genAppBar('生成结果'),
      body: ResultPageBody(
        taskId: taskId,
        preferKind: AssetKind.image,
        hero: _hero,
        successActions: _successActions,
        failureActions: _failureActions,
      ),
    );
  }

  /// 主视觉：按图片自己的比例铺开
  ///
  /// 【为什么比例要夹一下】宽高来自服务端，是不可信输入（见 `WorkGrid._ratioOf`
  /// 里同样的处理）。这一页比网格更宽容一点（网格是并排两列，必须严格），
  /// 但也不能让一张 1:5 的长图占掉五屏 —— 那样下面的提示词和积分说明
  /// 就永远滚不到了。夹在 0.5~2.0 之间只会裁掉极端比例的一点点。
  static Widget _hero(BuildContext context, Task task, Asset asset) {
    final ratio = (asset.aspectRatio ?? 1.0).clamp(0.5, 2.0);

    return AspectRatio(
      aspectRatio: ratio,
      child: AiGeneratedFrame(
        // 用大卡片的圆角：这是整页的主视觉，不是缩略图
        radius: AppRadius.card,
        child: Image.network(
          asset.publicUrl,
          fit: BoxFit.cover,
          width: double.infinity,
          height: double.infinity,
          // 静态占位，不是转圈（理由见 `work_thumbnail.dart`）
          loadingBuilder: (context, child, progress) =>
              progress == null ? child : const _ImagePlaceholder(),
          // 【必须接住】Mock 阶段的地址（mock-oss.local）根本不存在，
          // 断网时也一定失败。不接住就是一片红。
          errorBuilder: (context, error, stack) => const _ImagePlaceholder(),
        ),
      ),
    );
  }

  static List<Widget> _successActions(
    BuildContext context,
    Task task,
    Asset asset,
  ) {
    return [
      GenActionButton(
        key: const Key('result.toVideo'),
        label: '做成视频',
        icon: Icons.movie_creation_outlined,
        // 【为什么把 asset.id 传过去而不是 task.id】视频接口要的是
        // `source_asset_id` —— 参考图是**资产**，不是任务。
        // 传错了后端会报「参考图不存在」，而那种错在客户端看起来毫无头绪。
        //
        // 【为什么连提示词一起带过去】因为「让这张图动起来」最自然的写法
        // 就是在原来那句描述上加一点运动（「…奔跑」→「…慢慢跑向镜头」）。
        // 不带的话用户要从零再打一遍，而视频这一页是**要花钱**的那一步，
        // 让他在这里多打 20 个字，等于多一次放弃的机会。
        // （另一条路 —— 视频结果页的「再做一条」—— 也是这么带的，两处一致。）
        onTap: () => Navigator.of(context).push<void>(
          AppRoutes.videoGenRoute<void>(
            sourceAssetId: asset.id,
            prompt: task.prompt,
          ),
        ),
      ),
      const SizedBox(height: 10),
      GenActionButton(
        key: const Key('result.again'),
        label: '用同样的描述再生成一张',
        icon: Icons.refresh,
        filled: false,
        // 带着原提示词回到生成页 —— 用户改两个字再试是最常见的动作
        onTap: () => Navigator.of(context).push<void>(
          AppRoutes.imageGenRoute<void>(prompt: task.prompt),
        ),
      ),
    ];
  }

  static List<Widget> _failureActions(BuildContext context, Task task) {
    return [
      GenActionButton(
        key: const Key('result.retry'),
        label: '重新生成',
        icon: Icons.refresh,
        // 【为什么是 pushReplacement 而不是 push】这一页是一张已经作废的
        // 「结果页」，把它留在栈里没有意义 —— 用户返回时不该先看到
        // 「这次没成功」，然后再退一次才回到首页。
        onTap: () => Navigator.of(context).pushReplacement<void, void>(
          AppRoutes.imageGenRoute<void>(prompt: task.prompt),
        ),
      ),
    ];
  }
}

/// 图片的静态占位（加载中 / 失败共用）
class _ImagePlaceholder extends StatelessWidget {
  const _ImagePlaceholder();

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.center,
      color: AppColors.sunken,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.image_outlined,
            size: 30,
            color: AppColors.taupe.withValues(alpha: 0.55),
          ),
          const SizedBox(height: 10),
          Text(
            // 【为什么要给一句话，而不是只放一个图标】图片是这一页的全部内容。
            // 只放一个淡淡的图标，用户分不清是「还在加载」还是「图片没了」——
            // 给他一句话，他就知道该怎么办（等一会儿，或者下拉刷新）。
            '图片还没加载出来',
            style: TextStyle(
              fontSize: 12,
              color: AppColors.taupe.withValues(alpha: 0.8),
            ),
          ),
        ],
      ),
    );
  }
}
