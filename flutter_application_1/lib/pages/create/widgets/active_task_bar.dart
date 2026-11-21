import 'package:flutter/material.dart';

import '../../../models/task.dart';
import '../../../theme/app_theme.dart';
import '../../../widgets/glass_card.dart';

/// 首页顶部的「进行中任务条」
///
/// 只在**确实有**排队中/生成中的任务时出现；没有任务时它渲染成空，
/// 占位都不占，所以首页看起来和以前一样。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么必须有这一条】
/// 视频生成约 10 分钟（工程文档 §8.4）。移动端不能用一整个转圈的页面
/// 去承载 10 分钟等待 —— 用户要能离开这一屏继续别的事，
/// 所以把「有几个任务在跑」常驻在首页顶部，随时看一眼进度。
///
/// 【为什么这里没有进度条】
/// 这是**刻意的**。生成耗时由 provider 侧的 Agent 决定，我们拿不到真实百分比，
/// 画一个匀速前进的进度条就是在撒谎。所以这里只显示三件我们知道的事：
/// 在做什么、处于哪个阶段、排在什么位置（§8.2「诚实显示排队位次，不做假进度条」）。
///
/// ─────────────────────────────────────────────────────────
/// 【B6 改了它的入参：从「四个散字段」改成「一个 Task」】
///
/// 原来是 `prompt` / `statusLabel` / `queuePosition` 三个字段分开传，
/// 因为 B1 阶段还没有任务模型，画的是**假数据**。
/// 现在真数据是 `Task`，如果还让调用方把字段一个个拆出来传，
/// 那么「状态 → 文案」的翻译就会散在调用方那里 ——
/// 而首页、作品页、结果页三处都要做同一件事，迟早会不一致
/// （比如一处把 submitted 说成「生成中」、另一处说成「已提交」）。
///
/// 现在给它 `Task`，它自己去看 `status.label` 和 `queuePosition`。
///
/// 【它读的仍然是服务端的值，不是 App 存的状态】
/// 这个 `Task` 是 `activeTasksProvider` 刚从服务端拉回来的**一份拷贝**，
/// 用完就扔。组件**不留**它 —— 见 §8.4：App 内存里不许有任务状态的"真身"。
/// ─────────────────────────────────────────────────────────
class ActiveTaskBar extends StatelessWidget {
  const ActiveTaskBar({
    super.key,
    this.task,
    this.activeCount = 0,
    this.onTap,
  });

  /// 要展示的那一个任务。为 null 表示没有进行中的任务 —— 整条不出现。
  ///
  /// 【为什么只展示一个】这一条是「一条横幅」，不是列表。
  /// 要逐个看的话，作品页的「进行中」分段才是那个地方（而且能取消）。
  final Task? task;

  /// 一共有几个进行中。大于 1 时在副标题里说一句「共 N 个进行中」——
  /// 否则用户会以为「它只做了一个，另外两个我没让它做啊」。
  final int activeCount;

  /// 点击进入任务详情
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final task = this.task;
    if (task == null) return const SizedBox.shrink();

    // 有排队位次就报位次（§8.2 唯一诚实的等待信息）；
    // 没有就只说状态 —— 已经在跑的任务前面没有人，
    // 而「前面还有 0 个」会让用户以为马上就出结果。
    final subtitle = <String>[
      task.status.label,
      if (task.queuePosition != null) '前面还有 ${task.queuePosition} 个',
      if (activeCount > 1) '共 $activeCount 个进行中',
    ].join(' · ');

    return Padding(
      // CSS: 与上下区块的节奏一致
      padding: const EdgeInsets.only(bottom: 14),
      child: GlassCard(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: GestureDetector(
          onTap: onTap,
          // opaque：整条都可点，不只是文字那几个像素
          behavior: HitTestBehavior.opaque,
          child: Row(
            children: [
              // 沙漏图标 = 「在等」，不用进度条
              const Icon(Icons.hourglass_top, size: 18, color: AppColors.gold),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      task.prompt,
                      maxLines: 1,
                      // 长了就省略号，不要撑破整条
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: AppColors.charcoal,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        fontSize: 11.5,
                        color: AppColors.taupe,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.chevron_right,
                size: 18,
                color: AppColors.taupe,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
