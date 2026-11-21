import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../../models/asset.dart';
import '../../models/task.dart';
import '../../providers/asset_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ai_generated_badge.dart';
import 'widgets/gen_parts.dart';
import 'widgets/result_body.dart';
import 'widgets/video_evidence_card.dart';

/// 视频结果页
///
/// ─────────────────────────────────────────────────────────
/// 【为什么视频不是「一进来就自动播」】
///
/// 三个理由，最后一个是硬约束：
///
/// 1. **流量**。用户点开一条 10 秒的 720P 视频，自动播就要下几 MB。
///    他可能只是想看一眼构图像不像，不想为了这个花流量。
/// 2. **打扰**。在公共场合突然出声，是很没礼貌的一件事。
/// 3. **widget 测试**：`VideoPlayerController.initialize()` 要过平台通道，
///    测试环境里根本没有这个通道。只要它在 `initState` 里被调用，
///    这一页的所有测试都会挂 —— 而且报的是一个和 UI 无关的平台错误。
///    做成「点了才初始化」，测试就永远碰不到它。
///
/// 所以这一页进来先是一张**封面图 + 播放按钮**，点了才开始加载。
/// ─────────────────────────────────────────────────────────
class VideoResultPage extends ConsumerStatefulWidget {
  const VideoResultPage({super.key, required this.taskId});

  final String taskId;

  @override
  ConsumerState<VideoResultPage> createState() => _VideoResultPageState();
}

class _VideoResultPageState extends ConsumerState<VideoResultPage> {
  /// 播放器。**点了播放之后才有值** —— 见类注释第 3 条。
  VideoPlayerController? _controller;

  bool _loading = false;

  /// 播放失败了（视频文件拉不到、格式不支持、演示环境的地址是假的）。
  ///
  /// 【为什么要单独存一句错误，而不是让它静默失败】因为用户点的是
  /// 屏幕中间那个大播放按钮 —— 那是整页最显眼的东西。
  /// 点了没反应，他的结论是「这 App 坏了」，而不是「这段视频有问题」。
  String? _playError;

  @override
  void dispose() {
    // 【必须 dispose】播放器占着解码器和内存，不释放会泄漏 ——
    // 用户来回进出几次结果页，内存就下不来了。
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _play(Asset video) async {
    setState(() {
      _loading = true;
      _playError = null;
    });

    final controller = VideoPlayerController.networkUrl(
      Uri.parse(video.publicUrl),
    );

    try {
      await controller.initialize();
      await controller.setLooping(true);
      await controller.play();

      if (!mounted) {
        // 加载过程中用户退出了这一页 —— 刚建好的播放器没人管，就地销毁
        await controller.dispose();
        return;
      }
      setState(() {
        _controller = controller;
        _loading = false;
      });
    } on Object {
      await controller.dispose();
      if (!mounted) return;
      setState(() {
        _loading = false;
        // 【不把原始异常拼进来】异常文本是给开发看的（可能是
        // 「PlatformException(VideoError, ...)」）。用户需要知道的只有
        // 「这段视频暂时放不了」，以及这件事**不影响他的作品还在**。
        _playError = '这段视频暂时播不了。文件还在，可以稍后再试一次。';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: genAppBar('生成结果'),
      body: ResultPageBody(
        taskId: widget.taskId,
        preferKind: AssetKind.video,
        hero: _hero,
        successActions: _successActions,
        failureActions: _failureActions,
      ),
    );
  }

  Widget _hero(BuildContext context, Task task, Asset video) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _stage(task, video),
        if (_playError != null) ...[
          const SizedBox(height: 10),
          GenErrorBar(message: _playError!),
        ],
        VideoEvidenceCard(assetId: video.id),
      ],
    );
  }

  Widget _stage(Task task, Asset video) {
    final controller = _controller;

    // ── 已经在播 ────────────────────────────────────────────
    if (controller != null) {
      final ratio = controller.value.aspectRatio;
      return AspectRatio(
        // 有些编码拿不到宽高比（返回 0），那时退到 16:9 而不是除零
        aspectRatio: ratio > 0 ? ratio : 16 / 9,
        child: AiGeneratedFrame(
          radius: AppRadius.card,
          // 播放器本体。标识由 AiGeneratedFrame 压在上面 ——
          // 视频**正在播**的时候标识也必须可见（§10.1 要的是画面上的标识，
          // 而画面就是这里）。
          child: VideoPlayer(controller),
        ),
      );
    }

    // ── 还是封面 ────────────────────────────────────────────
    return AspectRatio(
      aspectRatio: (video.aspectRatio ?? 16 / 9).clamp(0.5, 2.0),
      child: AiGeneratedFrame(
        radius: AppRadius.card,
        child: Stack(
          children: [
            // 封面是**另一个资产**（`thumbnail`），所以它要自己再查一次 ——
            // 见 `_Poster` 的注释
            _Poster(taskId: widget.taskId),
            Positioned.fill(
              child: Center(
                child: _PlayButton(
                  loading: _loading,
                  onTap: () => _play(video),
                ),
              ),
            ),
          ],
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
        key: const Key('result.again'),
        label: '再做一条',
        icon: Icons.refresh,
        filled: false,
        onTap: () => Navigator.of(context).push<void>(
          AppRoutes.videoGenRoute<void>(
            // 【为什么把参考图一起带过去】一条视频的参考图就是它自己的首帧
            // 那一类的图（`source_asset_id`）。带上它，用户点「再做一条」
            // 之后不用重新选图，改一句描述就能再提交。
            sourceAssetId: task.sourceAssetId,
            prompt: task.prompt,
          ),
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
        onTap: () => Navigator.of(context).pushReplacement<void, void>(
          AppRoutes.videoGenRoute<void>(
            sourceAssetId: task.sourceAssetId,
            prompt: task.prompt,
          ),
        ),
      ),
    ];
  }
}

/// 视频封面
///
/// 【为什么要单独一个组件】因为它要 `ref.watch` 一个 provider
/// （`taskAssetProvider` 取这个任务的 `thumbnail`），而 `_stage` 是普通方法 ——
/// 普通方法里没有 `ref`。把需要 watch 的那一小块做成组件，是 Riverpod 里
/// 最省事的解法。
class _Poster extends ConsumerWidget {
  const _Poster({required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final poster = ref.watch(
      taskAssetProvider(
        TaskAssetQuery(taskId: taskId, preferKind: AssetKind.thumbnail),
      ),
    );

    final url = poster.value?.publicUrl;

    // 封面还没拉到（或这个任务没有封面）时，也不是空白 ——
    // 空白会被当成「这里坏了」，一块深色底 + 一句话就够。
    if (url == null || url.isEmpty) {
      return const ColoredBox(
        color: AppColors.sunken,
        child: SizedBox.expand(),
      );
    }

    return Image.network(
      url,
      fit: BoxFit.cover,
      width: double.infinity,
      height: double.infinity,
      loadingBuilder: (context, child, progress) =>
          progress == null ? child : const ColoredBox(color: AppColors.sunken),
      errorBuilder: (context, error, stack) =>
          const ColoredBox(color: AppColors.sunken),
    );
  }
}

/// 大播放按钮
///
/// 【为什么加载中不转圈】还是那条理由：转圈是永不停止的动画，
/// 会让 widget 测试的 `pumpAndSettle()` 超时（见 `async_section.dart`）。
/// 这里换成一个文字「加载中…」，同时把按钮变成不可点 ——
/// 防的是用户连点五次，建出五个播放器。
class _PlayButton extends StatelessWidget {
  const _PlayButton({required this.loading, required this.onTap});

  final bool loading;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      key: const Key('result.play'),
      onTap: loading ? null : onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        decoration: BoxDecoration(
          color: const Color(0x8A000000),
          borderRadius: BorderRadius.circular(AppRadius.pill),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              loading ? Icons.hourglass_top : Icons.play_arrow_rounded,
              size: 22,
              color: Colors.white,
            ),
            const SizedBox(width: 6),
            Text(
              loading ? '加载中…' : '播放',
              style: const TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
