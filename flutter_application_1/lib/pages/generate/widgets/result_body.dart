import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/constants/task_status.dart';
import '../../../core/format/credit_format.dart';
import '../../../core/format/date_format.dart';
import '../../../core/format/task_copy.dart';
import '../../../models/asset.dart';
import '../../../models/task.dart';
import '../../../providers/asset_providers.dart';
import '../../../providers/task_providers.dart';
import '../../../theme/app_theme.dart';
import '../../../widgets/async_section.dart';
import '../../../widgets/glass_card.dart';
import '../../../widgets/task_status_chip.dart';

/// 结果页的公共骨架 —— 图片结果页和视频结果页只有一个地方不同：
/// **中间那块产物怎么画**（一张大图 vs 一个播放器）。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么两页要共用这个骨架，而不是各写一份】
///
/// 因为「还没好 / 好了 / 没成功」这三态的**判断逻辑和文案**必须一模一样。
/// 视频要十分钟，用户在这十分钟里会反复退出再进来 —— 他每次进来的
/// 心智是一样的：「我那个东西好了吗」。两条链路要是把「排队中」写成
/// 两种话术、或者只有一边显示了积分已退回，用户就会得到一个结论：
/// 这个 App 自己都不知道自己在干什么。
/// ─────────────────────────────────────────────────────────
///
/// 【为什么它能自己跟进，而不需要用户手动下拉】
///
/// 因为这一页常常是**刚提交完跳过来的**（`pushReplacement`），
/// 那一刻任务几乎一定还在排队。一个需要用户手动刷十分钟的页面
/// 等于没有这个页面。
///
/// 跟进的方式是**搭 App 外壳那次轮询的顺风车**：`ref.listen` 监听
/// `activeTasksProvider`，它一变（外壳每 5 秒 / 15 秒就更新它一次），
/// 这一页就重拉一次详情。这样有四个好处：
///   · 不用在这一页里再开一个 `Timer`（测试里多余的 Timer 会让
///     `pumpAndSettle` 报「A Timer is still pending」）；
///   · 页面关掉时它自动跟着停，没有任何东西需要手动清理；
///   · 全 App 只有一个心跳，不会出现「两个地方各自轮询、互相打断」；
///   · 任务一进终态就从 active 列表消失，这一页自然就不再刷新了。
/// ─────────────────────────────────────────────────────────
class ResultPageBody extends ConsumerWidget {
  const ResultPageBody({
    super.key,
    required this.taskId,
    required this.preferKind,
    required this.hero,
    required this.successActions,
    required this.failureActions,
  });

  final String taskId;

  /// 要哪种产物。视频任务会同时产出视频和封面两条记录，
  /// 拿错的话用户会看到一个「能播的封面」（见 `TaskAssetQuery.preferKind`）。
  final AssetKind preferKind;

  /// 成功时中间那块主视觉（大图 / 播放器）。
  final Widget Function(BuildContext context, Task task, Asset asset) hero;

  /// 成功时限定的操作（做成视频 / 再生成一张…）。
  final List<Widget> Function(BuildContext context, Task task, Asset asset)
      successActions;

  /// 没成功时的操作（重试）。
  final List<Widget> Function(BuildContext context, Task task) failureActions;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(taskDetailProvider(taskId));
    final notifier = ref.read(taskDetailProvider(taskId).notifier);

    // 见类注释：搭外壳轮询的顺风车
    ref.listen(activeTasksProvider, (previous, next) {
      final current = ref.read(taskDetailProvider(taskId)).value;
      // 已经到终态了就不用再刷 —— 任务状态不会再变，
      // 而这一页可能还要在用户手里放很久
      if (current == null || !current.status.isActive) return;
      notifier.refresh();
    });

    return AsyncSection<Task>(
      value: detail,
      onRetry: notifier.refresh,
      loading: const _ResultSkeleton(),
      builder: (context, task) => RefreshIndicator(
        onRefresh: notifier.refresh,
        color: AppColors.sage,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 32),
          children: [
            if (task.status == TaskStatus.succeeded)
              _SuccessSection(
                taskId: taskId,
                preferKind: preferKind,
                task: task,
                hero: hero,
                actions: successActions,
              )
            else ...[
              if (task.status.isActive)
                _WaitingNote(task: task)
              else
                _ProblemNote(task: task),
              ...failureActions(context, task),
            ],
            const SizedBox(height: 18),
            _MetaCard(task: task),
          ],
        ),
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 成功
// ────────────────────────────────────────────────────────────

/// 成功之后要**再问一次**「产物在哪」。
///
/// 【为什么要多这一次请求】因为任务详情接口**不返回产物**
/// （产物是 `assets` 表里独立的一行，见 §11.2）。两边靠 `task_id` 关联。
///
/// 【为什么要处理「任务成功了但产物是 null」】这是真实会发生的：
/// 后端在生成完成后要做一件事 —— 趁 provider 的 URL 还没过期（1 小时），
/// 把文件转存到我们自己的对象存储（§9.2）。那一小段时间里任务已经是
/// `succeeded`，但资产还没有。这时候**不能显示空白**，也不能说「失败」——
/// 要如实说「做好了，文件还在准备」。
class _SuccessSection extends ConsumerWidget {
  const _SuccessSection({
    required this.taskId,
    required this.preferKind,
    required this.task,
    required this.hero,
    required this.actions,
  });

  final String taskId;
  final AssetKind preferKind;
  final Task task;
  final Widget Function(BuildContext context, Task task, Asset asset) hero;
  final List<Widget> Function(BuildContext context, Task task, Asset asset)
      actions;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final query = TaskAssetQuery(taskId: taskId, preferKind: preferKind);
    final asset = ref.watch(taskAssetProvider(query));

    return AsyncSection<Asset?>(
      value: asset,
      onRetry: () async => ref.invalidate(taskAssetProvider(query)),
      loading: const _HeroSkeleton(),
      builder: (context, value) {
        if (value == null) return const _AssetNotReady();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            hero(context, task, value),
            const SizedBox(height: 16),
            ...actions(context, task, value),
          ],
        );
      },
    );
  }
}

/// 产物还没落地（见 `_SuccessSection` 的注释）
class _AssetNotReady extends StatelessWidget {
  const _AssetNotReady();

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 22),
      child: Column(
        children: [
          const Icon(Icons.inventory_2_outlined, size: 26, color: AppColors.sage),
          const SizedBox(height: 12),
          const Text(
            '生成好了，文件还在准备',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.charcoal,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            '成品要从生成服务那边转到我们的存储上，通常几秒钟。稍等一下，或者下拉刷新。',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, height: 1.6, color: AppColors.taupe),
          ),
        ],
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 还没好 / 没成功
// ────────────────────────────────────────────────────────────

/// 「还在跑」的说明
///
/// 【为什么这里连进度条都不画】§8.2：排队位次是唯一诚实的等待信息。
/// 一个匀速前进的进度条是编出来的 —— 视频要十分钟，前三十秒它爬到 5%、
/// 然后卡住不动，用户只会更焦虑。
class _WaitingNote extends StatelessWidget {
  const _WaitingNote({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        GlassCard(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  TaskStatusChip(status: task.status),
                  const SizedBox(width: 8),
                  Text(
                    '${task.kind.label} · ${formatRelativeTime(task.createdAt)}',
                    style: const TextStyle(fontSize: 12, color: AppColors.taupe),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              if (task.queuePosition != null)
                Text(
                  '前面还有 ${task.queuePosition} 个任务，排到之后才开始生成。',
                  style: const TextStyle(
                    fontSize: 13,
                    height: 1.6,
                    color: AppColors.charcoal,
                  ),
                )
              else
                const Text(
                  '正在生成，这个阶段的时间由模型决定，我们也拿不到准确的进度。',
                  style: TextStyle(
                    fontSize: 13,
                    height: 1.6,
                    color: AppColors.charcoal,
                  ),
                ),
              const SizedBox(height: 10),
              const Text(
                '不用停在这一页。退出去做别的事，做完会通知你，作品里也能找到。',
                style: TextStyle(
                  fontSize: 12,
                  height: 1.6,
                  color: AppColors.taupe,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 「没成功」的说明 + 积分去向
class _ProblemNote extends StatelessWidget {
  const _ProblemNote({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              TaskStatusChip(status: task.status),
              const SizedBox(width: 8),
              Text(
                '${task.kind.label} · ${formatRelativeTime(task.createdAt)}',
                style: const TextStyle(fontSize: 12, color: AppColors.taupe),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            // 和任务详情页同一句话（见 TaskCopy 的注释）
            TaskCopy.problemText(task.status) ?? '这次没有生成出结果。',
            style: const TextStyle(
              fontSize: 13,
              height: 1.65,
              color: AppColors.charcoal,
            ),
          ),
        ],
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 任务信息（三种状态都显示）
// ────────────────────────────────────────────────────────────

/// 提示词 + 这笔积分最后怎么了。
///
/// 【为什么两件事塞一张卡】它们是同一件事的两面：「我让它做了什么」
/// 和「它花了我多少」。对账的时候用户要同时看到这两个。
class _MetaCard extends StatelessWidget {
  const _MetaCard({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    final rows = <(String, String)>[
      if (task.params.ratio != null) ('比例', task.params.ratio!),
      if (task.params.duration != null) ('期望时长', '${task.params.duration} 秒'),
      if (task.outputDurationSec != null) ('成片时长', '${task.outputDurationSec} 秒'),
    ];

    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _MetaLabel('提示词'),
          const SizedBox(height: 8),
          SelectableText(
            task.prompt,
            style: const TextStyle(
              fontSize: 13.5,
              height: 1.65,
              color: AppColors.charcoal,
            ),
          ),
          if (rows.isNotEmpty) ...[
            const SizedBox(height: 16),
            const _MetaLabel('生成参数'),
            const SizedBox(height: 8),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    SizedBox(
                      width: 72,
                      child: Text(
                        row.$1,
                        style: const TextStyle(
                          fontSize: 12.5,
                          color: AppColors.taupe,
                        ),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        row.$2,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w500,
                          color: AppColors.charcoal,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
          const SizedBox(height: 16),
          const _MetaLabel('积分'),
          const SizedBox(height: 8),
          Text(
            CreditFormat.settlementText(task),
            style: const TextStyle(
              fontSize: 13,
              height: 1.6,
              color: AppColors.charcoal,
            ),
          ),
        ],
      ),
    );
  }
}

class _MetaLabel extends StatelessWidget {
  const _MetaLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w600,
        color: AppColors.taupe,
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 骨架
// ────────────────────────────────────────────────────────────

/// 主视觉的加载骨架：一块和产物同形的灰块
class _HeroSkeleton extends StatelessWidget {
  const _HeroSkeleton();

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 1,
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.sunken,
          borderRadius: BorderRadius.circular(AppRadius.card),
        ),
      ),
    );
  }
}

/// 整页的加载骨架（详情还没回来时）
class _ResultSkeleton extends StatelessWidget {
  const _ResultSkeleton();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AspectRatio(
          aspectRatio: 1,
          child: Container(
            decoration: BoxDecoration(
              color: AppColors.sunken,
              borderRadius: BorderRadius.circular(AppRadius.card),
            ),
          ),
        ),
        const SizedBox(height: 18),
        const SkeletonLines(rows: 4),
      ],
    );
  }
}
