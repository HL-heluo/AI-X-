import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants/task_status.dart';
import '../../core/format/credit_format.dart';
import '../../core/format/date_format.dart';
import '../../models/asset.dart';
import '../../models/task.dart';
import '../../providers/asset_providers.dart';
import '../../providers/shell_providers.dart';
import '../../providers/task_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/async_section.dart';
import '../../widgets/task_status_chip.dart';
import '../../widgets/work_grid.dart';

/// 作品（底部第 2 个 Tab）
///
/// 对应原型的 `works` + `taskHistory`（接单记录）合并而来。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么把「任务中心」并进作品页，而不是单开一个 Tab】
/// 「进行中」和「已完成」本质是同一批内容的不同状态 —— 一个是还在跑的生成任务，
/// 一个是跑完留下来的图片/视频。用分段控件切换比多开一个 Tab 更符合认知，
/// 而且三个 Tab 是移动端的舒适上限。
///
/// ─────────────────────────────────────────────────────────
/// 【「已完成」这一段为什么要摆两种东西】
///
/// 因为**「作品」和「记录」不是同一件事**，而用户两件都要看：
///
///   · **作品**（图片/视频网格）：他做出来的东西，用来回看、预览、拿去用。
///     数据来源是 `GET /assets`。
///   · **没成功的那些记录**：失败了、被拒了、他取消了的。
///     这些**没有产物**，所以在网格里根本不会出现 ——
///     但用户必须能看到它们，尤其是要知道积分退回来了
///     （见 §7.4 的退费政策和 `TaskRepository.fetchDone` 的注释）。
///
/// 只摆网格的话，用户会遇到最坏的一种体验：花了积分、什么都没做出来、
/// 界面上一点痕迹都没有。他只会认为钱没了。
/// ─────────────────────────────────────────────────────────
///
/// 【数据来源提醒】任务状态**必须**从服务端拉（通过 provider），
/// 不能存在这个页面的 State 里 —— 用户关掉 App 再打开时，
/// 进行中的任务要能原样恢复（见 §8.4）。
/// 这个页面唯一的本地状态是「现在看的是哪一段」，那和任务无关。
///
/// ─────────────────────────────────────────────────────────
/// 【B6：「看哪一段」也从 State 搬到了 provider】
///
/// 首页的「最近作品」右边有个「全部 ›」，它要切到**这一页的「已完成」分段**。
/// 那个状态原来住在 `_WorksPageState` 里，别的页面写不进去 ——
/// 详见 `worksSegmentProvider` 的注释（那是这次搬迁的完整理由）。
///
/// 于是这个页面回落成了 `ConsumerWidget`：它现在**一点自己的状态都没有**，
/// 连刷新要把哪个分段的数据重拉，都是读 provider 得来的。
/// ─────────────────────────────────────────────────────────
class WorksPage extends ConsumerWidget {
  const WorksPage({super.key});

  Future<void> _refresh(WidgetRef ref) async {
    // 【为什么要按当前分段刷新】因为下拉刷新的语义是「我看到的这些，
    // 给我最新的」。用户在「已完成」上拉，期待的是作品和记录更新，
    // 顺手把进行中那份也刷一遍没有害处，但那份列表常常是空的 ——
    // 空列表刷新完什么都没变，用户会以为刷新坏了。
    if (ref.read(worksSegmentProvider) == WorksSegmentNotifier.active) {
      await ref.read(activeTasksProvider.notifier).refresh();
    } else {
      await Future.wait([
        ref.read(userAssetsProvider.notifier).refresh(),
        ref.read(doneTasksProvider.notifier).refresh(),
        if (ref.exists(certifiedAssetsProvider))
          ref.read(certifiedAssetsProvider.notifier).refresh(),
      ]);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final segment = ref.watch(worksSegmentProvider);

    return SafeArea(
      // bottom: false —— 底部是 Tab 栏，它自己会处理安全区
      bottom: false,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('我的作品', style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 14),
                Align(
                  alignment: Alignment.centerLeft,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 460),
                    child: _SegmentBar(
                      selected: segment,
                      onChanged: (i) =>
                          ref.read(worksSegmentProvider.notifier).select(i),
                    ),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () => _refresh(ref),
              color: AppColors.sage,
              child: ListView(
                // 内容不满一屏时 ListView 默认不可滚，RefreshIndicator 就拉不动
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 28),
                children: [
                  if (segment == WorksSegmentNotifier.active)
                    const _ActiveSection()
                  else
                    const _DoneSection(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 「进行中 / 已完成」分段控件
///
/// 【为什么和首页那个模式切换长得像，却是两份代码】
/// 因为它们的**职责不同**：首页那个切的是「我现在要做什么」（提交前），
/// 这个切的是「我要看哪一批」（提交后）。共用一份会逼出一堆
/// 「在首页模式下不显示角标」之类的开关参数，还不如各写各的 ——
/// 反正两边加起来也就几十行，而颜色、圆角、动效都取自同一套 token。
class _SegmentBar extends StatelessWidget {
  const _SegmentBar({required this.selected, required this.onChanged});

  final int selected;
  final ValueChanged<int> onChanged;

  static const List<String> _labels = ['进行中', '已完成'];

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.sunken,
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final pillWidth = constraints.maxWidth / _labels.length;

          return Stack(
            children: [
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
              Row(
                children: [
                  for (var i = 0; i < _labels.length; i++)
                    Expanded(
                      child: GestureDetector(
                        key: Key('works.segment.$i'),
                        onTap: () => onChanged(i),
                        behavior: HitTestBehavior.opaque,
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 9),
                          child: Text(
                            _labels[i],
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 13.5,
                              fontWeight: i == selected
                                  ? FontWeight.w600
                                  : FontWeight.w500,
                              color: i == selected
                                  ? AppColors.charcoal
                                  : AppColors.taupe,
                            ),
                          ),
                        ),
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

// ────────────────────────────────────────────────────────────
// 进行中
// ────────────────────────────────────────────────────────────

class _ActiveSection extends ConsumerWidget {
  const _ActiveSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final active = ref.watch(activeTasksProvider);

    return AsyncSection<List<Task>>(
      value: active,
      onRetry: ref.read(activeTasksProvider.notifier).refresh,
      loading: const _TileSkeleton(rows: 2),
      builder: (context, tasks) {
        if (tasks.isEmpty) {
          return const _Empty(
            icon: Icons.hourglass_empty,
            title: '现在没有进行中的任务',
            hint: '去「创作」页写一句提示词，生成的进度会出现在这里',
          );
        }

        return Column(
          children: [
            for (final task in tasks) ...[
              _ActiveTaskTile(task: task),
              const SizedBox(height: 10),
            ],
            const SizedBox(height: 6),
            const _HonestWaitNote(),
          ],
        );
      },
    );
  }
}

/// 一条进行中的任务
class _ActiveTaskTile extends StatelessWidget {
  const _ActiveTaskTile({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    // 有排队位次就显示位次，没有就只说状态。
    // 【为什么位次为 null 时不显示「前面还有 0 个」】见 §8.2：
    // 已经在跑的任务前面没有人，但「0 个」会让用户以为马上就出结果。
    final subtitle = task.queuePosition == null
        ? task.status.label
        : '${task.status.label} · 前面还有 ${task.queuePosition} 个';

    return _Card(
      key: Key('works.active.${task.id}'),
      onTap: () =>
          Navigator.of(context)
              .push<void>(AppRoutes.taskDetailRoute<void>(task.id)),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    TaskStatusChip(status: task.status),
                    const SizedBox(width: 6),
                    Text(
                      task.kind.label,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.taupe,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  task.prompt,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 13.5,
                    height: 1.45,
                    color: AppColors.charcoal,
                  ),
                ),
                const SizedBox(height: 6),
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
          const Icon(Icons.chevron_right, size: 20, color: AppColors.taupe),
        ],
      ),
    );
  }
}

/// 一句实话：等待是正常的，可以去别处逛。
///
/// 【为什么要专门写一段话】视频要十分钟。一个只显示「生成中」的页面
/// 会让人以为必须停在这里等 —— 于是他就真的盯着屏幕等十分钟。
/// §8.4 的设计意图是「用户可以离开」，那就得说出来。
class _HonestWaitNote extends StatelessWidget {
  const _HonestWaitNote();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(
        children: [
          const Icon(Icons.info_outline, size: 14, color: AppColors.taupe),
          const SizedBox(width: 6),
          const Expanded(
            child: Text(
              '视频通常要几分钟。你可以退出这个页面，做完会通知你',
              style: TextStyle(
                fontSize: 11.5,
                height: 1.5,
                color: AppColors.taupe,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 已完成
// ────────────────────────────────────────────────────────────

class _DoneSection extends ConsumerStatefulWidget {
  const _DoneSection();

  @override
  ConsumerState<_DoneSection> createState() => _DoneSectionState();
}

class _DoneSectionState extends ConsumerState<_DoneSection> {
  bool _certifiedOnly = false;

  @override
  Widget build(BuildContext context) {
    final provider = _certifiedOnly
        ? certifiedAssetsProvider
        : userAssetsProvider;
    final assets = ref.watch(provider);
    final done = ref.watch(doneTasksProvider);

    return Column(
      // 【为什么要挂一个 key】首页的「全部 ›」要切到这一段，测试要能断言
      // 「真的落在已完成了」。`works.segment.1` 那种 key 在这页里**一直存在**
      // （分段控件本身不随分段变化），断言不到分段到底切没切。
      key: const Key('works.done.body'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: FilterChip(
            label: const Text('已存证'),
            selected: _certifiedOnly,
            onSelected: (value) => setState(() => _certifiedOnly = value),
          ),
        ),
        AsyncSection<UserAssetsState>(
          value: assets,
          onRetry: ref.read(provider.notifier).refresh,
          loading: const _TileSkeleton(rows: 3),
          builder: (context, state) {
            final works = state.works;

            if (works.isEmpty) {
              // 【为什么这里不直接 return 空状态】因为「没有作品」和
              // 「有作品但都没成功」是两种完全不同的处境，
              // 而后者要靠下面那个列表说明。空状态只在这一段真的空时才给。
              return _Empty(
                icon: Icons.grid_view_outlined,
                title: _certifiedOnly ? '还没有已存证的作品' : '还没有作品',
                hint: _certifiedOnly
                    ? 'Fabric 确认后的成片会出现在这里'
                    : '生成出来的图片和视频会出现在这里',
              );
            }

            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                WorkGrid(
                  assets: works,
                  coverUrlOf: state.coverUrlOf,
                  onTap: (asset) => _openAsset(context, asset),
                ),
                if (state.hasMore) ...[
                  const SizedBox(height: 14),
                  _LoadMore(
                    loading: state.loadingMore,
                    onTap: () async {
                      final ok = await ref.read(provider.notifier).loadMore();
                      if (!ok && context.mounted) {
                        // 【为什么要提示】翻页失败时列表**保持原样**
                        // （见 UserAssetsNotifier.loadMore），如果不说话，
                        // 用户只会觉得「点了没反应」。
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('没拉到更多作品，稍后再试')),
                        );
                      }
                    },
                  ),
                ],
              ],
            );
          },
        ),
        const SizedBox(height: 26),
        _UnfinishedRecords(done: done),
      ],
    );
  }

  /// 点开一件作品。
  ///
  /// 【为什么进的是「结果页」而不是「任务详情」】因为用户点开一件作品，
  /// 想看的是**作品本身**（大图、播放），不是任务的排队历史和结算明细。
  /// 详情页从结果页里进得去，反过来就不顺。
  ///
  /// 【B6：这个判断搬去了 `AppRoutes.assetResultRoute`】因为首页的
  /// 「最近作品」点同一件东西也要做同一个决定。留在这儿各写一份，
  /// 迟早会变成「首页点进去是视频、作品页点进去是图片」。
  static void _openAsset(BuildContext context, Asset asset) {
    final route = AppRoutes.assetResultRoute(asset);
    if (route == null) return;
    Navigator.of(context).push<void>(route);
  }
}

/// 「没成功的那些记录」
class _UnfinishedRecords extends StatelessWidget {
  const _UnfinishedRecords({required this.done});

  final AsyncValue<List<Task>> done;

  @override
  Widget build(BuildContext context) {
    return AsyncSection<List<Task>>(
      value: done,
      loading: const _TileSkeleton(rows: 2),
      builder: (context, tasks) {
        // 【为什么要排除 succeeded】成功的那批已经在上面变成网格里的作品了。
        // 两处都显示的话，同一件事会出现两次，而用户会开始怀疑
        // 「是不是做了两遍，扣了两次钱」。
        final unfinished = tasks
            .where((t) => t.status != TaskStatus.succeeded)
            .toList(growable: false);

        if (unfinished.isEmpty) return const SizedBox.shrink();

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const _SectionLabel('没有生成成功的记录'),
            const SizedBox(height: 10),
            for (final task in unfinished) ...[
              _UnfinishedRow(task: task),
              const SizedBox(height: 8),
            ],
          ],
        );
      },
    );
  }
}

/// 一条没成功的记录。
///
/// 【为什么每条都要把「积分退回来了」写出来】因为这是用户最关心的一件事。
/// §7.4 定的政策是「排队中取消全额退、已提交后取消不退」——
/// 两种情况在界面上必须能区分出来，否则用户没法判断自己那次到底花了钱没有。
/// 文案由 `CreditFormat.settlementText` 统一给（全项目一份）。
class _UnfinishedRow extends StatelessWidget {
  const _UnfinishedRow({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context) {
    return _Card(
      key: Key('works.unfinished.${task.id}'),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: () =>
          Navigator.of(context)
              .push<void>(AppRoutes.taskDetailRoute<void>(task.id)),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    TaskStatusChip(status: task.status, compact: true),
                    const SizedBox(width: 6),
                    Text(
                      formatRelativeTime(task.lastTransitionAt),
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.taupe,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  task.prompt,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.charcoal,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  CreditFormat.settlementText(task),
                  style: const TextStyle(
                    fontSize: 11.5,
                    color: AppColors.taupe,
                  ),
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right, size: 18, color: AppColors.taupe),
        ],
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────
// 公共零件
// ────────────────────────────────────────────────────────────

/// 白底圆角卡片的统一外壳（这个页面上所有列表项都是它）
class _Card extends StatelessWidget {
  const _Card({
    super.key,
    required this.child,
    required this.onTap,
    this.padding = const EdgeInsets.all(14),
  });

  final Widget child;
  final VoidCallback onTap;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppGlass.tile,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppGlass.border, width: 1),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A000000),
            blurRadius: 20,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: GestureDetector(
        onTap: onTap,
        // opaque：整张卡可点，不只是文字那几个像素
        behavior: HitTestBehavior.opaque,
        child: Padding(padding: padding, child: child),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        color: AppColors.charcoal,
      ),
    );
  }
}

/// 空状态
///
/// 【为什么不用 `PlaceholderBody`】那个是给「整页还没做」用的
/// （居中、占满一屏）。这里的空状态是**列表内部**的一段，
/// 撑满一屏会把下拉刷新挤出视野。
class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.title, required this.hint});

  final IconData icon;
  final String title;
  final String hint;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 54, horizontal: 20),
      child: Column(
        children: [
          Icon(icon, size: 34, color: AppColors.taupe.withValues(alpha: 0.6)),
          const SizedBox(height: 14),
          Text(
            title,
            style: const TextStyle(
              fontSize: 14.5,
              fontWeight: FontWeight.w600,
              color: AppColors.charcoal,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            hint,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 12.5,
              height: 1.6,
              color: AppColors.taupe,
            ),
          ),
        ],
      ),
    );
  }
}

/// 加载骨架：几张和真实卡片同形的灰块
///
/// 【为什么不能用转圈】见 `async_section.dart` 里那段：
/// 一个永不停止的动画会让 `pumpAndSettle` 直接超时。
class _TileSkeleton extends StatelessWidget {
  const _TileSkeleton({required this.rows});

  final int rows;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < rows; i++) ...[
          if (i > 0) const SizedBox(height: 10),
          Container(
            height: 76,
            decoration: BoxDecoration(
              color: AppColors.sunken,
              borderRadius: BorderRadius.circular(AppRadius.lg),
            ),
          ),
        ],
      ],
    );
  }
}

/// 「加载更多」按钮
class _LoadMore extends StatelessWidget {
  const _LoadMore({required this.loading, required this.onTap});

  final bool loading;
  final Future<void> Function() onTap;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: TextButton(
        key: const Key('works.loadMore'),
        // 【为什么加载中要禁用】不然连点两下会发两次请求。
        // （provider 里也有守卫，这里是第一道。）
        onPressed: loading ? null : onTap,
        child: Text(
          loading ? '加载中…' : '加载更多',
          style: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: AppColors.sage,
          ),
        ),
      ),
    );
  }
}
