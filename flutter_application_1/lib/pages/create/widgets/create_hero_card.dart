import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format/credit_format.dart';
import '../../../models/task.dart';
import '../../../providers/generation_providers.dart';
import '../../../theme/app_theme.dart';
import '../../../widgets/glass_card.dart';

/// 创作模式的下标
///
/// 【为什么要有这个名字】因为「选中的是第几个」这件事要在
/// [CreatePage]（决定跳到哪个生成页）和这一整个文件（切文案、切参数提示）
/// 之间来回传。写裸的 `0` / `1` 时，读代码的人得回头数一遍 `_modes` 才敢确定
/// 哪个是视频 —— 而数错一次就是「打的是图片、点出来的是视频」。
abstract final class CreateMode {
  /// 文生图（§12.1 的 `text_to_image`）。
  static const int image = 0;

  /// 图生视频（§12.1 的 `image_to_video`）。v1 没有文生视频。
  static const int video = 1;
}

/// 创作模式的两种形态
///
/// 【为什么要建这个类】和底部 Tab 栏的 `_TabSpec` 同一个思路：
/// 两种模式的「图标 + 文字」结构一样、只是值不同，写成列表 + 循环，
/// 以后加模式只加一行。
class _ModeSpec {
  const _ModeSpec({required this.label, required this.icon});

  final String label;
  final IconData icon;
}

/// 首页的创作输入卡（整屏最核心的一块）
///
/// 【前端类比】对应原型 `home()` 里的 `.hero-card`：
/// 毛玻璃外框里套着「模式切换 + 输入区 + 生成按钮」三段。
///
/// ─────────────────────────────────────────────────────────
/// 【B6：它变成 ConsumerWidget，而且输入框搬去了父组件】
///
/// 1. **输入框搬走了**。`TextEditingController` 现在由 [CreatePage] 持有，
///    因为下面「创作场景」那一排要往同一个输入框里补字。
///    两个组件要操作同一个 controller，它就得待在两者共同的父节点上。
///
/// 2. **它要看报价了**。生成按钮下面那句计费说明不能再写死
///    「计算中…」—— 那是「还没问到价」的意思，而这个页面现在**问得到**
///    （`GET /generation/cost`）。真实报价是个 `AsyncValue`，
///    要 `ref.watch` 才拿得到，所以这里必须是 Consumer*。
///
/// ─────────────────────────────────────────────────────────
/// 【B6：删掉了两样东西，都不是漏了】
///
/// * **参数快捷栏**（模型 / 比例 / 数量 / 风格 / 清晰度 五个带 ▾ 的胶囊）。
///   它们从 B1 起就是装饰：点了没有任何反应，而每个上面都有一个下拉箭头
///   明示「可以点」。留着等于在首页正中间摆五个假按钮。
///   更要紧的是**这些参数本来就不该在这里选**：
///   视频的时长、比例、清晰度在生成页上选（那里才有完整的报价联动），
///   而「模型」在 v1 里根本不可选 —— 用哪个 provider 由后端配置决定。
///   现在这里只留一句实话：「时长、比例、清晰度在下一步选」。
///
/// * **输入框底下那排小图标**（拍照 / 相册 / 滤镜 / 调节）。
///   四个都点不动。其中三个在 v1 里连对应的功能都没有
///   （没有滤镜、没有参数面板、没有系统相册选图 ——
///   见 `VideoGenPage` 类注释里对「为什么没有系统相册」的说明）。
///   真正有功能的那个（从自己的作品里选参考图）在**下一页**，
///   而「开始生成」这个按钮正好就是去那里 —— 再放一个去同一个地方的按钮
///   只会让人猜「这两个有什么区别」。
///
/// 【判断标准】一个按钮看起来能点、点了什么都不发生，比没有这个按钮更糟：
/// 用户会反复点、会以为 App 卡了，而且他会开始不信任**别的**按钮。
/// ─────────────────────────────────────────────────────────
class CreateHeroCard extends ConsumerWidget {
  const CreateHeroCard({
    super.key,
    required this.mode,
    required this.promptController,
    required this.onModeChanged,
    required this.onGenerate,
  });

  /// 当前模式，取值见 [CreateMode]。由父组件持有。
  final int mode;

  /// 提示词输入框。**由父组件持有** —— 见类注释。
  final TextEditingController promptController;

  final ValueChanged<int> onModeChanged;

  /// 点「开始生成」。去下一页选参数并提交。
  final VoidCallback onGenerate;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return GlassCard(
      // CSS: .hero-card { margin-bottom: 24px; padding: 6px; border-radius: 24px }
      margin: const EdgeInsets.only(bottom: 24),
      radius: AppRadius.hero,
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          _ModeTabRow(selected: mode, onChanged: onModeChanged),
          const SizedBox(height: 14),
          _PromptArea(controller: promptController),
          _ParamNote(mode: mode),
          _GenArea(mode: mode, onGenerate: onGenerate),
        ],
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 第 1 段：模式切换（图片 / 视频）
// ────────────────────────────────────────────────────────────

/// 分段控件 + 会滑动的白色指示块
///
/// 【这一轮从三个模式减到两个】
/// 原来第三个是「音频」。音频生成（BGM / TTS / 口播）整条技术线都不在 v1 范围里 ——
/// 它不属于「图/文生视频」这一类模型，而且 v1 没有任何音频产出需求。
///
/// 【说明】原型用的是 ◈ ▶ ♪ 三个 Unicode 符号，这里按项目既定规则
/// （见 glass_tab_bar 的注释）换成 Material 图标。
class _ModeTabRow extends StatelessWidget {
  const _ModeTabRow({required this.selected, required this.onChanged});

  final int selected;
  final ValueChanged<int> onChanged;

  static const List<_ModeSpec> _modes = [
    _ModeSpec(label: '图片', icon: Icons.image_outlined),
    _ModeSpec(label: '视频', icon: Icons.videocam_outlined),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      // CSS: .mode-row { padding: 4px; background: rgba(0,0,0,0.04) }
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.sunken,
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          // 这里拿到的 maxWidth 已经是「去掉 padding 4×2」之后的内容宽度，
          // 正好等于每个 pill 的宽度（CSS: calc((100% - 8px) / 2)）。
          final pillWidth = constraints.maxWidth / _modes.length;

          return Stack(
            children: [
              // 白色指示块。位置跟着选中项走，用 AnimatedPositioned 让它滑过去
              // 而不是「啪」地跳过去（≈ CSS transition）。
              AnimatedPositioned(
                duration: const Duration(milliseconds: 250),
                curve: Curves.easeOut,
                left: pillWidth * selected,
                top: 0,
                bottom: 0,
                width: pillWidth,
                child: Container(
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                    // CSS: box-shadow: 0 2px 8px rgba(0,0,0,0.07)
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x12000000),
                        blurRadius: 8,
                        offset: Offset(0, 2),
                      ),
                    ],
                  ),
                ),
              ),
              // 各 pill 叠在指示块上面（Stack 里后写的画在上面）
              Row(
                children: [
                  for (var i = 0; i < _modes.length; i++)
                    Expanded(
                      child: _ModePill(
                        key: Key('home.mode.$i'),
                        spec: _modes[i],
                        selected: i == selected,
                        onTap: () => onChanged(i),
                      ),
                    ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}

/// 单个模式 pill
class _ModePill extends StatelessWidget {
  const _ModePill({
    super.key,
    required this.spec,
    required this.selected,
    required this.onTap,
  });

  final _ModeSpec spec;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = selected ? AppColors.charcoal : AppColors.taupe;

    return GestureDetector(
      onTap: onTap,
      // opaque：整个 pill 区域都可点，不只是文字那几个像素
      behavior: HitTestBehavior.opaque,
      child: Padding(
        // CSS: .mode-pill { padding: 8px 0 }
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(spec.icon, size: 13, color: color),
            const SizedBox(width: 5),
            Text(
              spec.label,
              style: TextStyle(
                fontSize: 13,
                // 选中时加粗，视觉上更「实」
                fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 第 2 段：输入区
// ────────────────────────────────────────────────────────────

/// 输入区：真输入框
///
/// 【为什么这里没有第二层 BackdropFilter】
/// 它本来就压在一层已经糊过的毛玻璃上，再糊一次只会更浑浊，也更费性能。
/// 原型 `.prompt-area` 本身也只是半透明白底，没有 backdrop-filter。
class _PromptArea extends StatelessWidget {
  const _PromptArea({required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      // CSS: .prompt-area { min-height: 110px; padding: 14px 16px }
      constraints: const BoxConstraints(minHeight: 110),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: AppGlass.panel,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppGlass.borderSoft, width: 1),
      ),
      child: TextField(
        key: const Key('home.prompt'),
        controller: controller,
        // minLines/maxLines 一起用 = 从 2 行起、随内容长高、最多 6 行，
        // 再多的内容靠内部滚动。（maxLines: null 会无限长高，把卡片撑爆）
        minLines: 2,
        maxLines: 6,
        textInputAction: TextInputAction.newline,
        style: const TextStyle(
          fontSize: 15,
          color: AppColors.charcoal,
          height: 1.6,
        ),
        decoration: const InputDecoration(
          // 占位文案已去电商化：原来是「描述商品画面，如：白色背景，柔光，高级质感…」，
          // 那是给电商卖家看的。现在面向的是个人创作者。
          hintText: '描述你想要的画面，如：一只猫在沙滩上奔跑，逆光，电影感…',
          hintStyle: TextStyle(
            fontSize: 15,
            color: AppColors.taupe,
            height: 1.6,
          ),
          // 边框、内边距全部交给外层的 Container，
          // 否则 Material 会给它套一层自己的下划线/圆角框。
          border: InputBorder.none,
          enabledBorder: InputBorder.none,
          focusedBorder: InputBorder.none,
          filled: false,
          isDense: true,
          contentPadding: EdgeInsets.zero,
        ),
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 第 3 段：参数的说明（替代原来那排假胶囊）
// ────────────────────────────────────────────────────────────

/// 「参数在下一步选」这一句
///
/// 【为什么要有这一句】因为参数从首页搬走了（见类注释），
/// 不说明的话用户会以为这个 App 根本不能选时长/比例。
/// 这一句把「去哪儿选」交代清楚，代价是一行小字。
class _ParamNote extends StatelessWidget {
  const _ParamNote({required this.mode});

  final int mode;

  @override
  Widget build(BuildContext context) {
    return Padding(
      // CSS: 原 .param-quick-row { padding: 14px 2px 2px }
      padding: const EdgeInsets.fromLTRB(2, 14, 2, 0),
      child: Row(
        children: [
          const Icon(Icons.tune, size: 13, color: AppColors.taupe),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              mode == CreateMode.video ? '时长、比例、清晰度在下一步选' : '画面比例在下一步选',
              style: const TextStyle(fontSize: 11.5, color: AppColors.taupe),
            ),
          ),
        ],
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 第 4 段：生成按钮 + 计费说明
// ────────────────────────────────────────────────────────────

/// 生成按钮 + 下面的积分说明
///
/// 【为什么是 ConsumerWidget】按钮下那句说明来自 `GET /generation/cost`，
/// 是个异步值 —— 要 `ref.watch` 才拿得到。
class _GenArea extends ConsumerWidget {
  const _GenArea({required this.mode, required this.onGenerate});

  final int mode;
  final VoidCallback onGenerate;

  /// 要问的价。
  ///
  /// 【duration / ratio 为什么是 null】因为首页不选参数，
  /// 用户在下一页才选。传 null 表示「按默认参数问」——
  /// 后端会拿它自己的默认值算（Mock 里是 5 秒）。
  /// 所以这里显示的是一个**会随参数变化**的预估值，
  /// 下一句「在下一步选」正是为了说明这一点。
  CostQuery get _query => (
    kind: mode == CreateMode.video
        ? TaskKind.imageToVideo
        : TaskKind.textToImage,
    durationSec: null,
    ratio: null,
  );

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final estimate = ref.watch(costEstimateProvider(_query));

    // 三态，一句话都不许自己编 —— 见 `credit_format.dart`：
    //   data    → 区间 + 冻结额 + 多余退回的承诺
    //   loading → 「计算中…」
    //   error   → 「暂时拿不到报价 · 提交后按实际消耗结算」
    // 【为什么 error 不能退回「计算中…」】那会让用户以为再等等就有数字，
    // 而那个请求已经失败了、不会再回来。
    final hint = estimate.when(
      data: CreditFormat.generationHint,
      loading: () => CreditFormat.calculating,
      error: (_, _) => CreditFormat.costUnavailable,
    );

    return Padding(
      // CSS: .gen-area { padding: 14px 2px 6px }
      padding: const EdgeInsets.fromLTRB(2, 14, 2, 6),
      child: Column(
        children: [
          GestureDetector(
            key: const Key('home.generate'),
            onTap: onGenerate,
            behavior: HitTestBehavior.opaque,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 14),
              decoration: BoxDecoration(
                // CSS: linear-gradient(135deg, var(--sage), var(--gold))
                gradient: const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [AppColors.sage, AppColors.gold],
                ),
                borderRadius: BorderRadius.circular(AppRadius.pill),
                // CSS: box-shadow: 0 8px 24px rgba(124,154,126,0.28)
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x477C9A7E),
                    blurRadius: 24,
                    offset: Offset(0, 8),
                  ),
                ],
              ),
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.auto_awesome, size: 16, color: Colors.white),
                  SizedBox(width: 6),
                  Text(
                    '开始生成',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                      letterSpacing: 0.3, // ≈ CSS 的 0.02em
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 9),
          Text(
            hint,
            key: const Key('home.costHint'),
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 11, color: AppColors.taupe),
          ),
        ],
      ),
    );
  }
}
