import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../core/constants/error_codes.dart';
import '../../core/network/api_exception.dart';
import '../../models/asset.dart';
import '../../models/task.dart';
import '../../providers/asset_providers.dart';
import '../../providers/generation_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/async_section.dart';
import '../../widgets/work_thumbnail.dart';
import 'widgets/gen_parts.dart';

/// 视频生成页（§13.2 的 `videoGen`）
///
/// ─────────────────────────────────────────────────────────
/// 【v1 的视频是「图生视频」，不是文生视频】
///
/// 这是产品的主线顺序（§14.4）：**先出图，满意了再让图动起来**。
/// 所以这一页的必填项是「一张参考图 + 一句描述」，而不是只有描述。
///
/// 【参考图从哪来】
/// 只能从**用户自己生成过的图片**里选（见 [_SourceImageSheet]）。
/// 这一轮**不做系统相册**，理由有三条：
///
///   1. 技术线：§5 要求参考图必须公网可访问，所以任何一张图都要先走
///      `POST /uploads/image`。而 v1 的图是**生成出来的**，本来就在我们
///      自己的对象存储上 —— 选它反而零上传、零等待、也不会有「这张图的
///      版权是谁的」这类问题。
///   2. 产品线：主线就是「图 → 视频」。放开相册等于把「先出图」这一步
///      绕过去了，而那一步是刻意的设计（图片是入口，视频是卖点）。
///   3. 工程线：相册权限在 Web / Android / iOS 上三套逻辑，
///      而 v1 的交付形态是 APK 侧载 + Web 演示，这一轮不划算。
///
/// `POST /uploads/image` 仍然连着（见 `asset_repository.dart`），
/// 只是界面暂时没有入口 —— 等 C 阶段接了真后端再决定要不要放开。
/// ─────────────────────────────────────────────────────────
class VideoGenPage extends ConsumerStatefulWidget {
  const VideoGenPage({super.key, this.sourceAssetId, this.initialPrompt});

  /// 已经选好的参考图（从图片结果页「做成视频」过来时带着）。
  final String? sourceAssetId;

  /// 带过来的提示词。
  final String? initialPrompt;

  @override
  ConsumerState<VideoGenPage> createState() => _VideoGenPageState();
}

class _VideoGenPageState extends ConsumerState<VideoGenPage> {
  late final TextEditingController _prompt;

  /// 参考图的资产 id。
  ///
  /// 【为什么存 id 而不是 Asset 对象】因为要传给后端的就是这个 id
  /// （`source_asset_id`），而 Asset 对象可以从 `userAssetsProvider` 里查出来
  /// （见 [_sourceAssetOf]）。存 id 只有一个真身，不会出现
  /// 「界面上显示的是 A，提交上去的是 B」这种对不上的情况。
  late String? _sourceAssetId;

  int _durationSec = _durations.first.value;
  String _ratio = _ratios.first.value;

  /// v1 是否允许选 1080P。**默认关闭**。
  ///
  /// §14.1 定了 v1 先上 720P；§18-2 说 provider 的 1080P 实际能力
  /// 还没实机确认过（定价表里是 9 积分/秒，比 720P 贵一倍多）。
  /// 在没确认之前就让用户选，最坏的结果是「扣了 1080P 的钱、拿到 720P 的片」——
  /// 那是要退款的。所以这一项先物理性地关掉，卡实测过了把这里改成 true 即可。
  static const bool allow1080p = false;

  bool _submitting = false;
  AppException? _error;

  /// 本次「提交意图」的幂等键。完整生命周期见 `image_gen_page.dart` 的类注释 ——
  /// 两个页面是同一套规矩。
  String? _intentKey;

  static const List<GenChoice<int>> _durations = [
    GenChoice('5 秒', 5),
    GenChoice('10 秒', 10),
  ];

  static const List<GenChoice<String>> _ratios = [
    GenChoice('16:9', '16:9'),
    GenChoice('9:16', '9:16'),
    GenChoice('1:1', '1:1'),
  ];

  @override
  void initState() {
    super.initState();
    _sourceAssetId = widget.sourceAssetId;
    _prompt = TextEditingController(text: widget.initialPrompt ?? '');
    _prompt.addListener(_forgetIntent);
  }

  @override
  void dispose() {
    _prompt.removeListener(_forgetIntent);
    _prompt.dispose();
    super.dispose();
  }

  void _forgetIntent() {
    _intentKey = null;
  }

  CostQuery get _costQuery => (
        kind: TaskKind.imageToVideo,
        durationSec: _durationSec,
        ratio: _ratio,
      );

  /// 按 id 找出参考图那一份资产。
  ///
  /// 【为什么找不到就返回 null 而不是报错】从结果页带 id 过来时，
  /// 作品列表可能还没拉回来。那时我们**知道**用户选的是哪张图
  /// （id 在手上），只是暂时画不出它的缩略图 —— 界面上退化成
  /// 「已选一张参考图」，而不是把用户的选择清空。
  Asset? _sourceAssetOf(WidgetRef ref) {
    final id = _sourceAssetId;
    if (id == null) return null;
    final list = ref.watch(userAssetsProvider).value?.assets;
    if (list == null) return null;
    for (final a in list) {
      if (a.id == id) return a;
    }
    return null;
  }

  Future<void> _pickSourceImage() async {
    final picked = await showModalBottomSheet<Asset>(
      context: context,
      backgroundColor: AppColors.bgWarm,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.hero)),
      ),
      builder: (context) => const _SourceImageSheet(),
    );

    if (picked == null || !mounted) return;
    setState(() {
      _sourceAssetId = picked.id;
      _forgetIntent();
    });
  }

  Future<void> _submit() async {
    final prompt = _prompt.text.trim();
    final sourceId = _sourceAssetId;

    // 【为什么这里没有「没选图」的错误提示】因为按钮在那之前就是灰的 ——
    // 一个点不动的按钮 + 卡片上的「必选」两个字，比点下去再弹一句红字
    // 更早地把话说清楚。见 build 里的 enabled。
    if (sourceId == null) return;

    AppException? invalid;
    if (prompt.isEmpty || prompt.length > GenPromptField.maxLength) {
      invalid = localFormError(ApiErrorCode.invalidPrompt);
    }
    if (invalid != null) {
      setState(() => _error = invalid);
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      final task = await ref.read(generationSubmitterProvider).submitVideo(
            prompt: prompt,
            sourceAssetId: sourceId,
            idempotencyKey: _intentKey ??= const Uuid().v4(),
            durationSec: _durationSec,
            ratio: _ratio,
          );

      if (!mounted) return;
      _intentKey = null;
      await Navigator.of(context).pushReplacement<void, void>(
        AppRoutes.videoResultRoute<void>(task.id),
      );
    } on AppException catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _error = e;
      });
      await _handleSubmitError(e);
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _error = AppException(message: '提交时出现未预期的错误：$e');
      });
    }
  }

  Future<void> _handleSubmitError(AppException e) async {
    if (e.code != ApiErrorCode.insufficientCredits) return;

    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.bgWarm,
        title: const Text(
          '可用积分不足',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
        content: const Text(
          '视频按秒计费，下单时会先冻结一笔偏高的积分，生成完按成片实际时长结算，'
          '多冻结的部分自动退回。\n\n'
          '可用积分 = 总余额 − 冻结中。去积分页可以看到每一笔流水。',
          style: TextStyle(fontSize: 13.5, height: 1.6),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('知道了', style: TextStyle(color: AppColors.taupe)),
          ),
          TextButton(
            key: const Key('gen.errorAction'),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('去看积分', style: TextStyle(color: AppColors.sage)),
          ),
        ],
      ),
    );

    if (go != true || !mounted) return;
    await Navigator.of(context).push<void>(AppRoutes.creditsRoute<void>());
  }

  @override
  Widget build(BuildContext context) {
    final sourceAsset = _sourceAssetOf(ref);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: genAppBar('生成视频'),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 6, 20, 32),
        children: [
          GenCard(
            label: '参考图 · 必选',
            child: _SourceImageSlot(
              asset: sourceAsset,
              hasId: _sourceAssetId != null,
              onTap: _pickSourceImage,
              onClear: () => setState(() {
                _sourceAssetId = null;
                _forgetIntent();
              }),
            ),
          ),
          const SizedBox(height: 12),
          GenCard(
            label: '它要怎么动',
            child: GenPromptField(
              controller: _prompt,
              minLines: 3,
              hintText: '如：镜头缓缓推近，头发被风吹动，背景的光斑轻微闪烁…',
            ),
          ),
          const SizedBox(height: 12),
          GenCard(
            label: '时长',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GenChoiceRow<int>(
                  options: _durations,
                  value: _durationSec,
                  keyPrefix: 'gen.duration',
                  onChanged: (v) => setState(() {
                    _durationSec = v;
                    _forgetIntent();
                  }),
                ),
                const SizedBox(height: 10),
                const GenNotice(
                  text: '成片实际时长由模型决定，可能比选的略长一点点 —— '
                      '按实际时长结算，多冻结的会退回。',
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          GenCard(
            label: '画面比例',
            child: GenChoiceRow<String>(
              options: _ratios,
              value: _ratio,
              keyPrefix: 'gen.ratio',
              onChanged: (v) => setState(() {
                _ratio = v;
                _forgetIntent();
              }),
            ),
          ),
          const SizedBox(height: 12),
          GenCard(
            label: '清晰度',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 1080P 这个选项由 `allow1080p` 控制是否出现 ——
                // 关着的时候连占位都不给，免得用户去找一个按不动的按钮。
                if (allow1080p)
                  GenChoiceRow<String>(
                    options: const [
                      GenChoice('720P', '720p'),
                      GenChoice('1080P', '1080p'),
                    ],
                    value: '720p',
                    keyPrefix: 'gen.resolution',
                    onChanged: (_) {},
                  )
                else
                  const Row(
                    children: [
                      Icon(Icons.hd_outlined, size: 16, color: AppColors.sage),
                      SizedBox(width: 8),
                      Text(
                        '720P',
                        style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w600,
                          color: AppColors.charcoal,
                        ),
                      ),
                    ],
                  ),
                const SizedBox(height: 10),
                const GenNotice(
                  icon: Icons.science_outlined,
                  text: '高清（1080P）还在实机验证中，这一版先只开 720P。',
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          GenCard(
            label: '积分',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GenCostHint(query: _costQuery),
                const SizedBox(height: 8),
                const GenNotice(
                  text: '视频通常要几分钟。提交后可以退出这一页，做完会通知你。',
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          if (_error != null) ...[
            GenErrorBar(message: _error!.userMessage),
            const SizedBox(height: 12),
          ],
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: _prompt,
            builder: (context, value, _) => GenSubmitButton(
              label: '开始生成',
              busy: _submitting,
              // 两样都是必填：参考图决定「什么在动」，提示词决定「怎么动」。
              enabled: _sourceAssetId != null && value.text.trim().isNotEmpty,
              onTap: _submit,
            ),
          ),
        ],
      ),
    );
  }
}

/// 参考图槽位
///
/// 【为什么空着的时候要画一个虚线感的框】因为「这里需要一张图」
/// 这件事必须在**没选之前**就看得出来。一个纯文字的标签做不到这一点，
/// 用户会直接往下滑到按钮，然后疑惑按钮为什么是灰的。
class _SourceImageSlot extends StatelessWidget {
  const _SourceImageSlot({
    required this.asset,
    required this.hasId,
    required this.onTap,
    required this.onClear,
  });

  final Asset? asset;

  /// 手上有没有 id。**和 `asset != null` 不是一回事** ——
  /// id 有但资产还没拉回来时，用户的「已选」状态必须保住（见 [_VideoGenPageState._sourceAssetOf]）。
  final bool hasId;

  final VoidCallback onTap;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    if (!hasId) {
      return GestureDetector(
        key: const Key('gen.source.empty'),
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Container(
          height: 132,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: AppGlass.panel,
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppGlass.borderSoft, width: 1),
          ),
          child: const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.add_photo_alternate_outlined,
                  size: 26, color: AppColors.sage),
              SizedBox(height: 8),
              Text(
                '选一张你生成过的图片',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.charcoal,
                ),
              ),
              SizedBox(height: 4),
              Text(
                '视频会以它为起点动起来',
                style: TextStyle(fontSize: 11.5, color: AppColors.taupe),
              ),
            ],
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 96,
              height: 96,
              child: GestureDetector(
                key: const Key('gen.source.selected'),
                onTap: onTap,
                behavior: HitTestBehavior.opaque,
                child: asset == null
                    // 只有 id、图片还没拉到 —— 给一个中性的块，
                    // 而不是一个空白（空白看起来像加载失败）
                    ? Container(
                        decoration: BoxDecoration(
                          color: AppColors.sunken,
                          borderRadius: BorderRadius.circular(AppRadius.lg),
                        ),
                        alignment: Alignment.center,
                        child: const Icon(Icons.image_outlined,
                            size: 22, color: AppColors.taupe),
                      )
                    : WorkThumbnail(
                        asset: asset!,
                        // 参考图本身就是图片资产，不存在「另找一张封面」这回事
                        coverUrl: null,
                        radius: AppRadius.lg,
                        showPlayMark: false,
                      ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '已选参考图',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.charcoal,
                    ),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    '它会作为视频的第一帧，后面的动作由你的描述决定。',
                    style: TextStyle(
                      fontSize: 11.5,
                      height: 1.5,
                      color: AppColors.taupe,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      _MiniAction(
                        key: const Key('gen.source.change'),
                        label: '换一张',
                        color: AppColors.sage,
                        onTap: onTap,
                      ),
                      const SizedBox(width: 12),
                      _MiniAction(
                        key: const Key('gen.source.clear'),
                        label: '去掉',
                        color: AppColors.taupe,
                        onTap: onClear,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _MiniAction extends StatelessWidget {
  const _MiniAction({
    super.key,
    required this.label,
    required this.color,
    required this.onTap,
  });

  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Text(
        label,
        style: TextStyle(
          fontSize: 12.5,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}

/// 选参考图的底部弹层
///
/// 【为什么给的是「你自己的作品」而不是系统相册】见 [VideoGenPage] 的类注释。
class _SourceImageSheet extends ConsumerWidget {
  const _SourceImageSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final assets = ref.watch(userAssetsProvider);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 拖动条：底部弹层的通用暗示，也方便往下甩着关掉
            Center(
              child: Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.divider,
                  borderRadius: BorderRadius.circular(AppRadius.pill),
                ),
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              '选一张参考图',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: AppColors.charcoal,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              '从你生成过的图片里选一张。',
              style: TextStyle(fontSize: 12.5, color: AppColors.taupe),
            ),
            const SizedBox(height: 14),
            ConstrainedBox(
              // 弹层最高占屏幕一半多一点 —— 再高就盖住了用户正在填的表单，
              // 他会忘记自己刚才写到哪儿了
              constraints: BoxConstraints(
                maxHeight: MediaQuery.sizeOf(context).height * 0.5,
              ),
              child: AsyncSection<UserAssetsState>(
                value: assets,
                onRetry: ref.read(userAssetsProvider.notifier).refresh,
                loading: const _PickerSkeleton(),
                builder: (context, state) {
                  // 只留图片：视频不能当参考图（§14.4 的主线是「图 → 视频」），
                  // 封面是视频的附属文件，也不是一张独立的作品。
                  final images = state.assets
                      .where((a) => a.kind == AssetKind.image)
                      .toList(growable: false);

                  if (images.isEmpty) {
                    return const Padding(
                      padding: EdgeInsets.symmetric(vertical: 40),
                      child: Column(
                        children: [
                          Icon(Icons.image_not_supported_outlined,
                              size: 28, color: AppColors.taupe),
                          SizedBox(height: 12),
                          Text(
                            '还没有可用的图片',
                            style: TextStyle(
                              fontSize: 13.5,
                              fontWeight: FontWeight.w600,
                              color: AppColors.charcoal,
                            ),
                          ),
                          SizedBox(height: 6),
                          Text(
                            '先去生成一张图片，再回来把它变成视频',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 12,
                              height: 1.6,
                              color: AppColors.taupe,
                            ),
                          ),
                        ],
                      ),
                    );
                  }

                  return GridView.builder(
                    shrinkWrap: true,
                    padding: EdgeInsets.zero,
                    gridDelegate:
                        const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 3,
                      mainAxisSpacing: 8,
                      crossAxisSpacing: 8,
                    ),
                    itemCount: images.length,
                    itemBuilder: (context, index) {
                      final asset = images[index];
                      return GestureDetector(
                        key: Key('gen.source.pick.${asset.id}'),
                        behavior: HitTestBehavior.opaque,
                        // 选中就把这张资产**返回**给调用方（`showModalBottomSheet`
                        // 的返回值就是 pop 的第二个参数）
                        onTap: () => Navigator.of(context).pop(asset),
                        child: WorkThumbnail(
                          asset: asset,
                          coverUrl: null,
                          compact: true,
                          showPlayMark: false,
                        ),
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 弹层的加载骨架：九宫格灰块（和真正的网格同形，加载完不会跳一下）
class _PickerSkeleton extends StatelessWidget {
  const _PickerSkeleton();

  @override
  Widget build(BuildContext context) {
    return GridView.builder(
      shrinkWrap: true,
      padding: EdgeInsets.zero,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 3,
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
      ),
      itemCount: 6,
      itemBuilder: (context, index) => Container(
        decoration: BoxDecoration(
          color: AppColors.sunken,
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
      ),
    );
  }
}
