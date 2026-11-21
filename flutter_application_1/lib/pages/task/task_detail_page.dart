import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants/task_status.dart';
import '../../core/format/credit_format.dart';
import '../../core/format/date_format.dart';
import '../../core/format/task_copy.dart';
import '../../core/network/api_exception.dart';
import '../../models/task.dart';
import '../../providers/task_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/async_section.dart';
import '../../widgets/glass_card.dart';
import '../../widgets/task_status_chip.dart';

/// 任务详情
///
/// ─────────────────────────────────────────────────────────
/// 【为什么构造参数是 taskId 而不是 Task 对象】
///
/// 这是这一屏最重要的一条设计决定。传一个 `Task` 对象进来，等于
/// 把**打开那一刻的快照**钉在了页面上：用户盯着它的时候任务早就跑完了，
/// 页面还显示「生成中」，下拉刷新也无从刷新（手里只有一个死对象）。
///
/// 只传 id，页面就只能去服务端要 —— 而这正是 §8.4 要的：
/// 「任务生命周期完全归服务端，客户端只是观察者」。
///
/// 顺带一个好处：通知点进来的时候（将来做深链）只需要一个 id，
/// 不需要先把整个任务拉好再传进来。
/// ─────────────────────────────────────────────────────────
class TaskDetailPage extends ConsumerWidget {
  const TaskDetailPage({super.key, required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(taskDetailProvider(taskId));
    final notifier = ref.read(taskDetailProvider(taskId).notifier);

    return Scaffold(
      backgroundColor: Colors.transparent,
      // 【为什么这一页用自己的 AppBar，而首页那边没有】
      // 因为它是 push 上来的二级页，需要一个「返回」。首页是 Tab 的分支，
      // 没有可返回的地方。
      appBar: AppBar(
        title: const Text('任务详情'),
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        titleTextStyle: const TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w600,
          color: AppColors.charcoal,
        ),
        iconTheme: const IconThemeData(color: AppColors.charcoal),
      ),
      body: AsyncSection<Task>(
        value: detail,
        onRetry: notifier.refresh,
        builder: (context, task) => RefreshIndicator(
          onRefresh: notifier.refresh,
          color: AppColors.sage,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(20, 6, 20, 32),
            children: [_DetailBody(task: task)],
          ),
        ),
      ),
    );
  }
}

class _DetailBody extends ConsumerWidget {
  const _DetailBody({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _StatusHead(task: task),
        const SizedBox(height: 16),
        _PromptCard(task: task),
        const SizedBox(height: 12),
        _ParamCard(task: task),
        const SizedBox(height: 12),
        _BillingCard(task: task),
        if (task.status == TaskStatus.succeeded) ...[
          const SizedBox(height: 20),
          _PrimaryAction(
            label: task.kind == TaskKind.textToImage ? '查看图片' : '查看视频',
            onTap: () => Navigator.of(context).push<void>(
              task.kind == TaskKind.textToImage
                  ? AppRoutes.imageResultRoute<void>(task.id)
                  : AppRoutes.videoResultRoute<void>(task.id),
            ),
          ),
        ],
        if (task.status.isActive) ...[
          const SizedBox(height: 20),
          _CancelAction(task: task),
        ],
        const SizedBox(height: 18),
        _TimelineCard(task: task),
      ],
    );
  }
}

/// 顶部：状态 + 类型 + 排队位次
class _StatusHead extends StatelessWidget {
  const _StatusHead({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    return Column(
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
        // 【排队位次只在真的在排队时出现】见 §8.2 和
        // `Task.queuePosition` 的注释：拿不到位次时不显示这一行，
        // 而不是显示成「前面还有 0 个」—— 那会让用户以为马上就出结果。
        if (task.queuePosition != null) ...[
          const SizedBox(height: 12),
          GlassCard(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(
              children: [
                const Icon(Icons.hourglass_top, size: 16, color: AppColors.amber),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '前面还有 ${task.queuePosition} 个任务，排到之后才开始生成',
                    style: const TextStyle(
                      fontSize: 12.5,
                      height: 1.5,
                      color: AppColors.charcoal,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
        // 失败/被拒时给出「为什么」。errorMsg 是给开发看的原始信息，
        // 这里按状态给一句人话，原始信息不进界面。
        if (_problemText != null) ...[
          const SizedBox(height: 12),
          GlassCard(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(
              children: [
                const Icon(Icons.error_outline, size: 16, color: AppColors.danger),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _problemText!,
                    style: const TextStyle(
                      fontSize: 12.5,
                      height: 1.6,
                      color: AppColors.charcoal,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  // 文案取自 `TaskCopy` —— 结果页要说同一句话，两处各写一份迟早会漂移
  String? get _problemText => TaskCopy.problemText(task.status);
}

/// 提示词
class _PromptCard extends StatelessWidget {
  const _PromptCard({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('提示词'),
          const SizedBox(height: 8),
          // 【为什么不限制行数】详情页就是用户回来核对「我当时让它做什么」的地方，
          // 截断会让这个页面失去意义。
          SelectableText(
            task.prompt,
            style: const TextStyle(
              fontSize: 14,
              height: 1.65,
              color: AppColors.charcoal,
            ),
          ),
        ],
      ),
    );
  }
}

/// 生成参数
class _ParamCard extends StatelessWidget {
  const _ParamCard({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    final rows = <(String, String)>[
      ('类型', task.kind.label),
      if (task.params.ratio != null) ('比例', task.params.ratio!),
      if (task.params.duration != null) ('期望时长', '${task.params.duration} 秒'),
      // 【为什么成片时长和期望时长要分开显示】因为它们是两个数，
      // 而这两个数的差正是「为什么要按实际时长结算」的全部原因（§7.2）。
      if (task.outputDurationSec != null) ('成片时长', '${task.outputDurationSec} 秒'),
      if (task.params.width != null && task.params.height != null)
        ('分辨率', '${task.params.width}×${task.params.height}'),
    ];

    return GlassCard(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('生成参数'),
          const SizedBox(height: 10),
          for (var i = 0; i < rows.length; i++) ...[
            if (i > 0) const SizedBox(height: 8),
            Row(
              children: [
                SizedBox(
                  width: 72,
                  child: Text(
                    rows[i].$1,
                    style: const TextStyle(fontSize: 12.5, color: AppColors.taupe),
                  ),
                ),
                Expanded(
                  child: Text(
                    rows[i].$2,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: AppColors.charcoal,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// 计费
class _BillingCard extends StatelessWidget {
  const _BillingCard({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('积分'),
          const SizedBox(height: 10),
          // 下单前是「本次冻结 X~Y 积分…」，结束后是「本次消耗 X 积分，已退回 Y 积分」。
          // 两句话都由 CreditFormat 给 —— 全项目一份，见那个文件的注释。
          Text(
            CreditFormat.settlementText(task),
            style: const TextStyle(
              fontSize: 13.5,
              height: 1.6,
              color: AppColors.charcoal,
            ),
          ),
        ],
      ),
    );
  }
}

/// 取消任务
class _CancelAction extends ConsumerWidget {
  const _CancelAction({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return OutlinedButton(
      key: const Key('task.cancel'),
      onPressed: () => _confirmAndCancel(context, ref),
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(vertical: 13),
        side: const BorderSide(color: AppColors.divider),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.pill),
        ),
      ),
      child: const Text(
        '取消任务',
        style: TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w600,
          color: AppColors.danger,
        ),
      ),
    );
  }

  Future<void> _confirmAndCancel(BuildContext context, WidgetRef ref) async {
    // ─────────────────────────────────────────────────────────
    // 【退款提示必须按状态分开写】
    //
    // §7.4 的退费政策是**分档**的：
    //   · `pending` / `queued` 取消 → 全额退回（还没交给生成服务，没花钱）
    //   · 已 `submitted` 取消 → **不退**（生成服务已经在跑，钱已经花出去了）
    //
    // 如果一律写「取消会全额退回」，用户就会在第二种情况下被扣钱 ——
    // 这类「说好退却没退」是最容易引发投诉和退款申请的问题，
    // 严格来说属于我们对用户的虚假陈述。
    //
    // 所以这里不只是文案不同：**不该退的情况要多给一句劝阻**。
    // 让用户在知道代价的前提下再决定。
    // ─────────────────────────────────────────────────────────
    final refundable = task.status == TaskStatus.pending ||
        task.status == TaskStatus.queued;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.bgWarm,
        title: const Text(
          '取消这个任务？',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
        content: Text(
          refundable
              ? '它还在排队，取消后会全额退回 ${task.freezeAmount} ${CreditFormat.unit}。'
              : '它已经提交给生成服务了。现在取消**不会**退回积分，'
                  '而且再等一会儿可能就有结果了。',
          style: const TextStyle(fontSize: 13.5, height: 1.6),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('再等等', style: TextStyle(color: AppColors.sage)),
          ),
          TextButton(
            key: const Key('task.cancel.confirm'),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(
              refundable ? '取消并退回' : '仍然取消',
              style: const TextStyle(color: AppColors.danger),
            ),
          ),
        ],
      ),
    );

    if (confirmed != true || !context.mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(activeTasksProvider.notifier).cancel(task.id);
      // 取消成功后任务进终态，这一页的数据要重拉一次 ——
      // 否则界面还停在上面的「生成中」，用户会以为没取消掉。
      await ref.read(taskDetailProvider(task.id).notifier).refresh();
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            refundable
                ? '已取消，${task.freezeAmount} ${CreditFormat.unit}已退回'
                : '已取消',
          ),
        ),
      );
    } on AppException catch (e) {
      // 【为什么不吞掉】取消是真的会失败的（任务刚好跑完了、已经取消了）。
      // 那一刻用户正盯着按钮等结果，必须说清楚，不能转一下圈然后什么都没发生。
      messenger.showSnackBar(SnackBar(content: Text(e.userMessage)));
    }
  }
}

/// 时间线
class _TimelineCard extends StatelessWidget {
  const _TimelineCard({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    final rows = <(String, DateTime?)>[
      ('提交', task.createdAt),
      ('入队', task.queuedAt),
      ('开始生成', task.submittedAt),
      ('结束', task.finishedAt),
    ].where((r) => r.$2 != null).toList();

    if (rows.length < 2) return const SizedBox.shrink();

    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('时间'),
          const SizedBox(height: 10),
          for (var i = 0; i < rows.length; i++) ...[
            if (i > 0) const SizedBox(height: 8),
            Row(
              children: [
                SizedBox(
                  width: 72,
                  child: Text(
                    rows[i].$1,
                    style: const TextStyle(fontSize: 12.5, color: AppColors.taupe),
                  ),
                ),
                Expanded(
                  child: Text(
                    // 这里用**绝对时间**而不是「3 分钟前」：
                    // 时间线是用来对账的，「3 分钟前」对不了账。
                    '${formatDate(rows[i].$2)} ${_timeOfDay(rows[i].$2!)}',
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: AppColors.charcoal,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  /// 时分秒。不引 intl 就是为了这一个格式（见 date_format.dart 的说明）。
  static String _timeOfDay(DateTime t) {
    final local = t.toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${two(local.hour)}:${two(local.minute)}:${two(local.second)}';
  }
}

/// 主行动按钮（渐变胶囊，和生成按钮同款）
class _PrimaryAction extends StatelessWidget {
  const _PrimaryAction({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      key: const Key('task.primary'),
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [AppColors.sage, AppColors.gold],
          ),
          borderRadius: BorderRadius.circular(AppRadius.pill),
          boxShadow: const [
            BoxShadow(
              color: Color(0x477C9A7E),
              blurRadius: 24,
              offset: Offset(0, 8),
            ),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.visibility_outlined, size: 16, color: Colors.white),
            const SizedBox(width: 6),
            Text(
              label,
              style: const TextStyle(
                fontSize: 15,
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

/// 卡片里的小标题
class _Label extends StatelessWidget {
  const _Label(this.text);

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
