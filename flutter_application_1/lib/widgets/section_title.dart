import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 区块标题：「创作工具　　　　查看全部 ›」
///
/// 【为什么放在公共 widgets 里】
/// 首页现在就有两处（创作工具 / 最近作品），后面的「我的」「接单大厅」
/// 也都要用同一种标题。放这里，各页面直接引用，不用各抄一份。
///
/// 【前端类比】对应原型 CSS 的 `.section-title` + `.more`。
/// 左边标题 15px 加粗炭黑，右边次要文字 12px 灰褐。
class SectionTitle extends StatelessWidget {
  const SectionTitle({
    super.key,
    required this.title,
    this.action,
  });

  /// 左侧标题
  final String title;

  /// 右侧次要文字，比如「查看全部 ›」。
  /// 这一轮不做点击，所以它只是个字符串，不是按钮。
  final String? action;

  @override
  Widget build(BuildContext context) {
    return Padding(
      // CSS: margin: 4px 0 12px
      padding: const EdgeInsets.only(top: 4, bottom: 12),
      child: Row(
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: AppColors.charcoal,
              letterSpacing: -0.15, // ≈ CSS 的 letter-spacing: -0.01em（15px × -0.01）
            ),
          ),
          // Spacer 会把右边的元素顶到最右，等价于 CSS 的 justify-content: space-between
          const Spacer(),
          if (action != null)
            Text(
              action!,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w400,
                color: AppColors.taupe,
              ),
            ),
        ],
      ),
    );
  }
}
