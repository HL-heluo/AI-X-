/// 生成页（图片 / 视频）共用的零件
///
/// ─────────────────────────────────────────────────────────
/// 【为什么两个生成页要共用这一层，而首页那张卡不共用】
///
/// 首页那张输入卡是**入口**：它只负责问「你要做图片还是视频」，
/// 然后把用户带到这里。它不需要选项、不需要错误条、不需要提交中的状态。
///
/// 这两个页面才是**真正下单的地方**：要有参数选项、要有报价、
/// 要有提交失败的说明、要有「正在提交」。这些东西两个页面一模一样 ——
/// 各写一遍的话，「积分不足」在图片页和视频页迟早会变成两种说法，
/// 而计费文案一旦不一致，用户就会怀疑哪一句是真的。
///
/// 首页那张卡不强行改成用这一层，是因为它的形态差别太大
/// （毛玻璃大卡、内嵌分段控件、参数胶囊），套进来只会多出一堆开关参数。
/// ─────────────────────────────────────────────────────────
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/constants/error_codes.dart';
import '../../../core/format/credit_format.dart';
import '../../../core/network/api_exception.dart';
import '../../../providers/generation_providers.dart';
import '../../../theme/app_theme.dart';
import '../../../widgets/glass_card.dart';

/// 生成/结果这些二级页统一的 AppBar
///
/// 【为什么要抽出来】这四页（图片生成、视频生成、图片结果、视频结果）
/// 都从底部 Tab 的某个分支 push 上来，都需要「返回」。
/// 各写一遍的话，透明底、标题字号、图标颜色迟早会有两页不一样 ——
/// 而这种差别一旦出现，看起来就像「这两页不是一个人做的」。
AppBar genAppBar(String title, {List<Widget>? actions}) {
  return AppBar(
    title: Text(title),
    actions: actions,
    // 透明底 + 无阴影：底下是 AppBackground 的渐变，压一层不透明表面会把它切断
    backgroundColor: Colors.transparent,
    surfaceTintColor: Colors.transparent,
    elevation: 0,
    titleTextStyle: const TextStyle(
      fontSize: 16,
      fontWeight: FontWeight.w600,
      color: AppColors.charcoal,
    ),
    iconTheme: const IconThemeData(color: AppColors.charcoal),
  );
}

/// 客户端的就地校验失败。
///
/// 【为什么要造一个 AppException，而不是直接显示一句自己写的字符串】
/// 「提示词不能为空，且不超过 2000 字」这句话的**权威版本在后端的错误码表里**
/// （`ApiErrorCode.invalidPrompt.defaultMessage`）。如果这里另写一句，
/// 同一个错误就会出现两种文案：前端拦下时说一种，后端拦下时说另一种。
/// 用户看到的是同一次提交、两种说法。
///
/// 造一个带 code 的异常，`userMessage` 取到的就是那份权威文案。
AppException localFormError(ApiErrorCode code) =>
    AppException(code: code, message: '客户端就地校验：${code.wire}');

/// 一个可选项（标签 + 值）
///
/// 【为什么不用 record】因为要放进 `const` 列表里，而且这些选项是
/// 静态配置（比例、时长），不是临时算出来的数据。一个两字段的小类最清楚。
class GenChoice<T> {
  const GenChoice(this.label, this.value);

  final String label;
  final T value;
}

/// 一张带小标题的卡（生成页上所有的「一段」都是它）
class GenCard extends StatelessWidget {
  const GenCard({super.key, required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.taupe,
            ),
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }
}

/// 一排单选胶囊（比例、时长都用它）
///
/// 【为什么能换行】「1:1 / 4:3 / 3:4 / 16:9 / 9:16」五个胶囊在窄屏上
/// 一行放不下。用 `Wrap` 而不是横向滚动 —— 选项是**必须全部看见**的
/// （用户要比较才能选），滑出去两个就等于藏了两个。
class GenChoiceRow<T> extends StatelessWidget {
  const GenChoiceRow({
    super.key,
    required this.options,
    required this.value,
    required this.onChanged,
    required this.keyPrefix,
  });

  final List<GenChoice<T>> options;
  final T value;
  final ValueChanged<T> onChanged;

  /// 给每个胶囊一个稳定的 Key（`<prefix>.<value>`），供测试点击用。
  final String keyPrefix;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final option in options)
          _ChoicePill(
            key: Key('$keyPrefix.${option.value}'),
            label: option.label,
            selected: option.value == value,
            onTap: () => onChanged(option.value),
          ),
      ],
    );
  }
}

class _ChoicePill extends StatelessWidget {
  const _ChoicePill({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? AppColors.sage : AppGlass.panel,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: Border.all(
            color: selected ? AppColors.sage : AppGlass.borderSoft,
            width: 1,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
            color: selected ? Colors.white : AppColors.charcoal,
          ),
        ),
      ),
    );
  }
}

/// 提示词输入框
///
/// 【为什么带字数统计，而且只在快满时才出现】
/// 上限 2000 字是后端定的硬规则，用户不知道。平时不显示计数（安静），
/// 接近上限时才出现 —— 那时候它是有用的，之前它只是噪音。
class GenPromptField extends StatelessWidget {
  const GenPromptField({
    super.key,
    required this.controller,
    required this.hintText,
    this.minLines = 5,
  });

  final TextEditingController controller;
  final String hintText;
  final int minLines;

  /// 后端上限（§11.2）。和 `ApiErrorCode.invalidPrompt` 的文案是同一个数。
  static const int maxLength = 2000;

  /// 从多少字开始显示计数。
  static const int _counterThreshold = 1800;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppGlass.panel,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppGlass.borderSoft, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          TextField(
            key: const Key('gen.prompt'),
            controller: controller,
            minLines: minLines,
            maxLines: minLines + 6,
            textInputAction: TextInputAction.newline,
            style: const TextStyle(
              fontSize: 15,
              height: 1.6,
              color: AppColors.charcoal,
            ),
            decoration: InputDecoration(
              hintText: hintText,
              hintStyle: const TextStyle(
                fontSize: 15,
                height: 1.6,
                color: AppColors.taupe,
              ),
              // 边框和内边距交给外层 Container，否则 Material 会自己套一层
              border: InputBorder.none,
              enabledBorder: InputBorder.none,
              focusedBorder: InputBorder.none,
              filled: false,
              isDense: true,
              contentPadding: EdgeInsets.zero,
            ),
          ),
          // controller 本身就是个 ValueListenable，不必为此把整个页面变成
          // StatefulWidget、也不必在 setState 里重建输入框。
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: controller,
            builder: (context, value, _) {
              final n = value.text.characters.length;
              if (n < _counterThreshold) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  '$n / $maxLength',
                  style: TextStyle(
                    fontSize: 11.5,
                    color: n > maxLength ? AppColors.danger : AppColors.taupe,
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

/// 报价那一行 —— §13.4 唯一允许的写法在这里落地
///
/// ─────────────────────────────────────────────────────────
/// 【这里为什么有三态，而不是两态】
///
/// 很多人会写成「有报价就显示区间，没有就显示计算中…」。第三态是
/// **问价这个请求本身失败了**（断网、后端 500）。那时：
///   · 继续显示「计算中…」→ 用户会一直等一个永远不来的数字；
///   · 显示一个数字 → §13.4 明令禁止（那个数字必定是错的）。
/// 所以给第三句话「暂时拿不到报价 · 提交后按实际消耗结算」，
/// 那句话同时也是真的。
///
/// 【注意它 watch 的是 provider，不是 FutureProvider 的 .future】
/// watch 整个 AsyncValue 才能区分 loading 和 error。取 `.future` 会把
/// 这两态压成同一个「还没值」。
/// ─────────────────────────────────────────────────────────
class GenCostHint extends ConsumerWidget {
  const GenCostHint({super.key, required this.query, this.textAlign});

  final CostQuery query;
  final TextAlign? textAlign;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final estimate = ref.watch(costEstimateProvider(query));

    final text = estimate.when(
      data: CreditFormat.generationHint,
      loading: () => CreditFormat.calculating,
      error: (_, _) => CreditFormat.costUnavailable,
    );

    return Text(
      text,
      key: const Key('gen.costHint'),
      textAlign: textAlign,
      style: const TextStyle(
        fontSize: 11.5,
        height: 1.5,
        color: AppColors.taupe,
      ),
    );
  }
}

/// 「开始生成」按钮
///
/// ─────────────────────────────────────────────────────────
/// 【提交中为什么是文字而不是转圈】
/// 转圈是一个**永不停止**的动画，只要它在屏幕上，widget 测试的
/// `pumpAndSettle()` 就永远等不到静止（见 `async_section.dart` 里那段）。
/// 换成一个静态的「正在提交…」，测试能跑，用户也看得懂。
///
/// 而且提交本来就该是秒级的 —— 真转上十秒，用户需要知道的也不是
/// 「它在转」，而是「它在等我」。
/// ─────────────────────────────────────────────────────────
class GenSubmitButton extends StatelessWidget {
  const GenSubmitButton({
    super.key,
    required this.label,
    required this.busy,
    required this.enabled,
    required this.onTap,
  });

  final String label;
  final bool busy;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    // 禁用态用中性灰：一个「亮着但按不动」的渐变按钮比灰按钮更糟 ——
    // 用户会反复点它，然后以为 App 坏了。
    final active = enabled && !busy;

    return GestureDetector(
      key: const Key('gen.submit'),
      // 禁用时 onTap 传 null，手势直接穿透（也顺带挡住连点）
      onTap: active ? onTap : null,
      behavior: HitTestBehavior.opaque,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 15),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          gradient: active
              ? const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [AppColors.sage, AppColors.gold],
                )
              : null,
          color: active ? null : AppColors.sunken,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          boxShadow: active
              ? const [
                  BoxShadow(
                    color: Color(0x477C9A7E),
                    blurRadius: 24,
                    offset: Offset(0, 8),
                  ),
                ]
              : null,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.auto_awesome,
              size: 16,
              color: active ? Colors.white : AppColors.taupe,
            ),
            const SizedBox(width: 6),
            Text(
              busy ? '正在提交…' : label,
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.3,
                color: active ? Colors.white : AppColors.taupe,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 就地错误条（提交失败时出现在按钮上方）
///
/// 【为什么要能带一个动作】因为「积分不足」不是一句提示能解决的 ——
/// 用户需要去积分页看余额和流水。只说一句「积分不足」而不给去处，
/// 等于把他丢在原地。所以错误条支持一个 trailing 动作。
///
/// 【注意别在这里写「去充值」】v1 没有充值（§7.6），
/// 这个动作指向的是**积分页**（看余额和流水），不是充值页 ——
/// 那个页面不存在，写出来就是一个点不动的承诺。
class GenErrorBar extends StatelessWidget {
  const GenErrorBar({
    super.key,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('gen.error'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        // 【为什么不用纯红底】这里承载的是「可以修正的问题」，
        // 不是灾难。淡红底 + 红字足够醒目，也不会让人以为数据丢了。
        color: AppColors.danger.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.danger.withValues(alpha: 0.25)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 1),
            child: Icon(Icons.error_outline, size: 15, color: AppColors.danger),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                fontSize: 12.5,
                height: 1.5,
                color: AppColors.danger,
              ),
            ),
          ),
          if (actionLabel != null && onAction != null) ...[
            const SizedBox(width: 8),
            GestureDetector(
              key: const Key('gen.errorAction'),
              onTap: onAction,
              behavior: HitTestBehavior.opaque,
              child: Text(
                actionLabel!,
                style: const TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: AppColors.danger,
                  decoration: TextDecoration.underline,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// 结果页上的一个操作按钮
///
/// 【为什么一个组件带 `filled` 开关，而不是两个组件】因为它们的
/// 尺寸、圆角、字号、图标间距必须完全一致 —— 分成两个类，
/// 改其中一个的 padding 时另一个不会跟着改，结果就是两个按钮
/// 差了 2px。这种差别肉眼看得出来，但很难说清哪里不对。
class GenActionButton extends StatelessWidget {
  const GenActionButton({
    super.key,
    required this.label,
    required this.icon,
    required this.onTap,
    this.filled = true,
  });

  final String label;
  final IconData icon;
  final VoidCallback onTap;

  /// true = 渐变实心（页面上的主要动作），false = 白底描边（次要动作）。
  final bool filled;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          gradient: filled
              ? const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [AppColors.sage, AppColors.gold],
                )
              : null,
          color: filled ? null : AppGlass.tile,
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: filled ? null : Border.all(color: AppGlass.border, width: 1),
          boxShadow: filled
              ? const [
                  BoxShadow(
                    color: Color(0x477C9A7E),
                    blurRadius: 24,
                    offset: Offset(0, 8),
                  ),
                ]
              : null,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 16, color: filled ? Colors.white : AppColors.sage),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                fontSize: 14.5,
                fontWeight: FontWeight.w600,
                color: filled ? Colors.white : AppColors.charcoal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 一句说明（浅色、中性、不是错误）
class GenNotice extends StatelessWidget {
  const GenNotice({
    super.key,
    required this.text,
    this.icon = Icons.info_outline,
  });

  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 1),
          child: Icon(icon, size: 14, color: AppColors.taupe),
        ),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              fontSize: 11.5,
              height: 1.55,
              color: AppColors.taupe,
            ),
          ),
        ),
      ],
    );
  }
}
