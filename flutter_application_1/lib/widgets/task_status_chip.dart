import 'package:flutter/material.dart';

import '../core/constants/task_status.dart';
import '../theme/app_theme.dart';

/// 任务状态的小胶囊（排队中 / 生成中 / 已完成 / 生成失败……）
///
/// ─────────────────────────────────────────────────────────
/// 【为什么必须是一个共享组件】
/// 这个胶囊要在**四个地方**出现：首页进行中任务条、作品页的两个分段、
/// 任务详情、结果页。状态一共 8 种，如果各页面自己挑颜色，
/// 一定会出现「同一个 failed，作品页画红、详情页画灰」这种事 ——
/// 用户会以为是两种不同的失败。
///
/// 【颜色为什么不新增】
/// 设计系统（§3.3.1）已经冻结了色值，而它里面刚好够用：
///   * `sage`  绿 → 成功、进行中（都是「一切正常」）
///   * `amber` 琥珀 → 排队等待（「在等，不是坏了」）
///   * `danger` 红 → 失败、被拒（「你需要处理」）
///   * `taupe` 灰褐 → 已取消、已过期（「你自己停的 / 时间到了」，
///     不是系统出错，所以不给红色 —— 红色会让人以为出了问题）
/// 四个语义映射已经覆盖全部 8 种状态，没有任何理由新增色值。
/// ─────────────────────────────────────────────────────────
class TaskStatusChip extends StatelessWidget {
  const TaskStatusChip({super.key, required this.status, this.compact = false});

  final TaskStatus status;

  /// 紧凑样式：网格的格子上用，字号和内边距都小一档。
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final color = colorOf(status);

    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 6 : 9,
        vertical: compact ? 2 : 4,
      ),
      decoration: BoxDecoration(
        // 同色系的浅底 + 描边：比纯色块轻，不会把卡片压死
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(AppRadius.pill),
        border: Border.all(color: color.withValues(alpha: 0.35), width: 1),
      ),
      child: Text(
        // 文案取自 TaskStatus.label —— 全项目只有那一份状态文案
        status.label,
        style: TextStyle(
          fontSize: compact ? 9.5 : 11,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }

  /// 状态 → 颜色。**这是唯一的映射表**，见类注释。
  static Color colorOf(TaskStatus status) => switch (status) {
        TaskStatus.succeeded => AppColors.sage,
        TaskStatus.submitted => AppColors.sage,
        TaskStatus.pending => AppColors.amber,
        TaskStatus.queued => AppColors.amber,
        TaskStatus.failed => AppColors.danger,
        TaskStatus.rejected => AppColors.danger,
        TaskStatus.canceled => AppColors.taupe,
        TaskStatus.expired => AppColors.taupe,
      };
}
