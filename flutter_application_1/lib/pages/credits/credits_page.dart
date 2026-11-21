import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format/credit_format.dart';
import '../../core/format/date_format.dart';
import '../../models/chain_summary.dart';
import '../../models/credit_account.dart';
import '../../models/credit_ledger_entry.dart';
import '../../models/me_profile.dart';
import '../../providers/credit_providers.dart';
import '../../providers/me_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_background.dart';
import '../../widgets/async_section.dart';
import '../../widgets/glass_card.dart';
import '../../widgets/section_title.dart';

/// 积分：余额 + 流水（§13.2 的 `credits`）
///
/// ─────────────────────────────────────────────────────────
/// 【v1 是**只读**的：这一屏没有任何花钱或充值的入口】
///
/// §7.6 的充值档位标着「此处为 v3 预留」，而 v1 的积分只有一个来源：
/// 注册赠送。所以这一屏只做一件事 —— 把账本给用户看明白。
///
/// 【为什么值得为「看明白」单独做一屏】
/// 因为这套计费是**冻结 → 结算 → 退回**三段式的。用户下单时会看到
/// 可用余额少了一笔（冻结），过一会儿又多回来几积分（退回多余的部分）。
/// 如果只有余额数字、没有账本，这个行为看起来就像**随机扣钱**。
/// 账本是把「看起来像 bug 的行为」解释成「有规则的行为」的唯一手段。
/// ─────────────────────────────────────────────────────────
class CreditsPage extends ConsumerWidget {
  const CreditsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(meProfileProvider);
    final ledger = ref.watch(creditLedgerProvider);
    final chain = ref.watch(chainSummaryProvider);

    final meNotifier = ref.read(meProfileProvider.notifier);
    final ledgerNotifier = ref.read(creditLedgerProvider.notifier);

    return AppBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(title: const Text('积分')),
        body: RefreshIndicator(
          // 【为什么要两个一起刷】余额和流水是同一次消费的两面。
          // 只刷一边，用户会看到「余额少了 35」但流水里没有那一笔 ——
          // 那一瞬间的界面比不刷新更糟。
          // 链上凭证一起刷：否则用户会看到「余额变了、链上没变」的中间态。
          onRefresh: () async {
            ref.invalidate(chainSummaryProvider);
            await Future.wait([
              meNotifier.refresh(),
              ledgerNotifier.refresh(),
            ]);
          },
          color: AppColors.sage,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
            children: [
              AsyncSection<MeProfile>(
                value: profile,
                onRetry: meNotifier.refresh,
                loading: const SkeletonLines(rows: 2),
                builder: (context, me) => _BalanceCard(account: me.creditAccount),
              ),
              const SizedBox(height: 16),
              AsyncSection<ChainSummary>(
                value: chain,
                onRetry: () async => ref.invalidate(chainSummaryProvider),
                loading: const SkeletonLines(rows: 3),
                builder: (context, summary) => _ChainCard(summary: summary),
              ),
              const SizedBox(height: 22),
              const SectionTitle(title: '全部明细'),
              AsyncSection<CreditLedgerState>(
                value: ledger,
                onRetry: ledgerNotifier.refresh,
                loading: const SkeletonLines(rows: 4),
                builder: (context, state) => _LedgerList(
                  state: state,
                  onLoadMore: ledgerNotifier.loadMore,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 余额总览：可用 / 冻结 / 总额。
class _BalanceCard extends StatelessWidget {
  const _BalanceCard({required this.account});

  final CreditAccount account;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '可用${CreditFormat.unit}',
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: AppColors.taupe,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            CreditFormat.balanceText(account.available),
            style: const TextStyle(
              fontSize: 32,
              fontWeight: FontWeight.w700,
              color: AppColors.gold,
              height: 1.1,
            ),
          ),
          const SizedBox(height: 14),
          const Divider(height: 1),
          const SizedBox(height: 12),
          // 【为什么把「总额」和「冻结中」也列出来】
          // 只有「可用」的话，用户会问「我明明有 80，怎么只显示 45」。
          // 三个数摆在一起，减法自己就成立了 —— 不需要文字解释。
          Row(
            children: [
              _MiniStat(
                label: CreditFormat.unit,
                value: '${account.balance}',
              ),
              _MiniStat(
                label: '冻结中',
                value: '${account.frozen}',
                // 冻结是**暂时用不了**，不是出错，所以用中性色而不是红/黄
                muted: account.frozen == 0,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MiniStat extends StatelessWidget {
  const _MiniStat({required this.label, required this.value, this.muted = false});

  final String label;
  final String value;

  /// 数值为 0 时压暗 —— 它是「没有」而不是「有 0 个」，不该抢注意力。
  final bool muted;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 11.5, color: AppColors.taupe),
          ),
          const SizedBox(height: 3),
          Text(
            value,
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: muted ? AppColors.taupe : AppColors.charcoal,
            ),
          ),
        ],
      ),
    );
  }
}

/// 流水列表 + 「加载更多」。
class _LedgerList extends StatelessWidget {
  const _LedgerList({required this.state, required this.onLoadMore});

  final CreditLedgerState state;
  final Future<bool> Function() onLoadMore;

  @override
  Widget build(BuildContext context) {
    if (state.entries.isEmpty) return const _EmptyLedger();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        GlassCard(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(
            children: [
              for (var i = 0; i < state.entries.length; i++) ...[
                if (i > 0) const Divider(height: 1, indent: 16, endIndent: 16),
                _LedgerRow(entry: state.entries[i]),
              ],
            ],
          ),
        ),
        if (state.hasMore) ...[
          const SizedBox(height: 14),
          _LoadMoreButton(
            loading: state.loadingMore,
            onTap: onLoadMore,
          ),
        ],
      ],
    );
  }
}

/// 一条流水。
class _LedgerRow extends StatelessWidget {
  const _LedgerRow({required this.entry});

  final CreditLedgerEntry entry;

  @override
  Widget build(BuildContext context) {
    // 【金额的符号由 kind 决定，不在这里自己判断】见 CreditFormat.ledgerAmountText：
    // 只有 settle 才减余额，freeze 写「冻结 40」**不带负号**。
    // 冻结带负号会让用户以为被扣了两次（冻结一次、结算一次）。
    final amountText = CreditFormat.ledgerAmountText(entry);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  // 备注优先（如「新用户注册赠送」），没有备注才退回类型名
                  entry.note?.isNotEmpty == true ? entry.note! : entry.kind.label,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                    color: AppColors.charcoal,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  // 有备注时把类型也带上，否则「结算」「退回」这些词就丢了
                  entry.note?.isNotEmpty == true
                      ? '${entry.kind.label} · ${formatRelativeTime(entry.createdAt)}'
                      : formatRelativeTime(entry.createdAt),
                  style: const TextStyle(
                    fontSize: 11.5,
                    color: AppColors.taupe,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(
            amountText,
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              // 【颜色跟着「这一笔动没动可用余额」走】冻结/退回不动可用余额（只动冻结额），
              // 用主色绿；真正的支出（settle）用炭黑；收入（赠送）用金色 ——
              // 和首页积分胶囊的语义一致，不新增色值。
              color: switch (entry.kind) {
                CreditLedgerKind.grant => AppColors.gold,
                CreditLedgerKind.settle => AppColors.charcoal,
                CreditLedgerKind.freeze ||
                CreditLedgerKind.refund ||
                CreditLedgerKind.adjust =>
                  AppColors.sage,
              },
            ),
          ),
        ],
      ),
    );
  }
}

/// 「加载更多」。
///
/// 【为什么是一个按钮，而不是滚到底自动加载】
/// 自动加载看起来更顺，但它需要一个滚动监听：监听器要防抖、
/// 要在「正在加载」时停止触发、还要在列表重建后重新挂上。
/// 这个项目里所有 widget 测试都用 `pumpAndSettle` 推进，
/// 而一个「滚到底就发请求」的监听器很容易变成测试里反复触发的循环。
/// 一个按钮：用户点、我们拉，行为完全可预测。
///
/// 【加载中为什么按钮变成禁用而不是转圈】见 `async_section.dart` 里那段 ——
/// 永久动画会让 `pumpAndSettle` 超时。这里改成文案变化。
class _LoadMoreButton extends StatelessWidget {
  const _LoadMoreButton({required this.loading, required this.onTap});

  final bool loading;
  final Future<bool> Function() onTap;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: TextButton(
        key: const Key('credits.loadMore'),
        onPressed: loading ? null : () => onTap(),
        style: TextButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 8),
        ),
        child: Text(
          loading ? '加载中…' : '加载更多',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w500,
            color: loading ? AppColors.taupe : AppColors.sage,
          ),
        ),
      ),
    );
  }
}

/// 一条流水都没有。
///
/// 【为什么文案要解释「为什么是空的」，而不是只说「暂无数据」】
/// 新注册的用户点进来必然是空的。「暂无数据」会让人怀疑是不是加载失败了；
/// 说清楚积分从哪来，用户就不用去别处找了。
class _EmptyLedger extends StatelessWidget {
  const _EmptyLedger();

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 28),
      child: Column(
        children: [
          const Icon(Icons.receipt_long_outlined,
              size: 28, color: AppColors.taupe),
          const SizedBox(height: 10),
          Text(
            '还没有${CreditFormat.unit}记录',
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w500,
              color: AppColors.charcoal,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            '开始创作后会在这里留下每一笔明细',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, height: 1.5, color: AppColors.taupe),
          ),
        ],
      ),
    );
  }
}

/// 链上凭证（方案 B 的影子链）。
///
/// 用户不需要信平台那句「积分在链上」——这里给出他自己能核对的三个东西：
/// 钱包地址、合约地址、以及每笔消耗/充值的交易哈希。
class _ChainCard extends StatelessWidget {
  const _ChainCard({required this.summary});

  final ChainSummary summary;

  @override
  Widget build(BuildContext context) {
    if (!summary.enabled) {
      return GlassCard(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
        child: Row(
          children: const [
            Icon(Icons.link_off, size: 16, color: AppColors.taupe),
            SizedBox(width: 8),
            Expanded(
              child: Text(
                '当前环境未开启链上映射（演示环境由后端 CHAIN_ENABLED 控制）',
                style: TextStyle(fontSize: 12, color: AppColors.taupe),
              ),
            ),
          ],
        ),
      );
    }

    final ok = summary.reconciled;
    return GlassCard(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.verified_outlined, size: 16, color: AppColors.sage),
              const SizedBox(width: 6),
              const Text(
                '链上凭证（影子链）',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.textBody,
                ),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: ok ? AppColors.sageTint : AppColors.bgPeach,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  summary.statusLabel,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: ok ? AppColors.sage : AppColors.amber,
                  ),
                ),
              ),
            ],
          ),
          if (summary.error != null) ...[
            const SizedBox(height: 8),
            Text(summary.error!, style: const TextStyle(fontSize: 11, color: AppColors.danger)),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              _MiniStat(label: '已确认 VCR', value: summary.onChainBalance?.toString() ?? '-'),
              _MiniStat(label: '账面总额', value: '${summary.ledgerBalance}'),
              _MiniStat(label: '站内可用', value: '${summary.availableBalance ?? summary.ledgerBalance}'),
            ],
          ),
          const SizedBox(height: 10),
          const Divider(height: 1),
          const SizedBox(height: 10),
          // 【地址一律给一键复制】用户要拿这两个地址去 Remix / 区块浏览器
          // 自己核对余额，手抄 42 位十六进制必然抄错一位 —— 而抄错的表现是
          // 「链上余额对不上」，看起来像平台在骗他。复制按钮堵的就是这个。
          _addressLine(
            label: '钱包',
            value: summary.address,
            copyKey: const Key('credits.copyWallet'),
          ),
          const SizedBox(height: 4),
          _addressLine(
            label: '合约',
            value: summary.contract,
            copyKey: const Key('credits.copyContract'),
          ),
          if (summary.recentOps.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text(
              '最近上链记录',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppColors.taupe),
            ),
            const SizedBox(height: 4),
            for (final op in summary.recentOps.take(3))
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '${op.kindLabel} ${op.amount} · '
                  '${op.txHash == null ? op.statusLabel : '${_short(op.txHash!)}（${op.statusLabel}）'}',
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.taupe,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }

  /// 一行「标签 + 地址」，地址有值时右侧带一个复制按钮。
  ///
  /// 【为什么不是「整行可点就复制」】
  /// 这一行的主要用途是**读**（用户对照着看地址开头/结尾对不对），复制是次要动作。
  /// 整行可点会让只想读的人误触，也会让这一行看起来像「点了会跳走」的链接 —— 它不是。
  /// 一个独立的小图标：想复制的人看得见，不想复制的人不会误触。
  ///
  /// 【地址为空时为什么连按钮一起藏掉】
  /// 空地址会渲染成 `-`，对 `-` 做复制毫无意义；而且后端在
  /// `CHAIN_ENABLED=1` 但钱包还没建好的那一瞬间确实会给出空值。
  Widget _addressLine({
    required String label,
    required String? value,
    required Key copyKey,
  }) {
    final hasValue = value != null && value.isNotEmpty;
    return Row(
      children: [
        SizedBox(
          width: 34,
          child: Text(
            label,
            style: const TextStyle(fontSize: 11, color: AppColors.taupe),
          ),
        ),
        Expanded(
          child: Text(
            hasValue ? value : '-',
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.textBody,
              fontFamily: 'monospace',
            ),
          ),
        ),
        if (hasValue)
          _CopyIconButton(key: copyKey, value: value, label: label),
      ],
    );
  }

  static String _short(String s) =>
      s.length <= 18 ? s : '${s.substring(0, 10)}…${s.substring(s.length - 6)}';
}

/// 一键复制：把地址写进剪贴板，并弹一句确认。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么要有它】
/// 影子链那一栏的地址是让用户**拿去自己核对**的（Remix / 区块浏览器里
/// 填 `balanceOf(钱包)`）。42 位十六进制手抄必错一位，而抄错的表现是
/// 「链上余额和平台余额对不上」—— 那不是「操作失误」，那是**看起来像平台做假账**。
/// 所以复制不是顺手加的便利，它是这个功能能不能被用起来的前提。
///
/// 【为什么先取 messenger 再 await】
/// `await Clipboard.setData(...)` 之后这一帧可能已经过去（用户点了就返回上一页），
/// 那时候再用 `ScaffoldMessenger.of(context)` 会拿到失效的 context 并抛错。
/// 先把它取出来存成局部变量，await 之后只碰这个变量，不碰 context。
///
/// 【为什么失败也要弹提示】
/// 剪贴板不是永远可用：Web 端的 `navigator.clipboard` 只在
/// 安全上下文（https 或 localhost）里存在，某些浏览器还会因为权限策略拒绝。
/// 那种情况下点了毫无反应，用户会以为按钮坏了 —— 告诉他「长按手动复制」才是出路。
/// ─────────────────────────────────────────────────────────
class _CopyIconButton extends StatelessWidget {
  const _CopyIconButton({
    super.key,
    required this.value,
    required this.label,
  });

  /// 要复制的完整地址（不是截断后的显示文本）。
  final String value;

  /// 用来拼提示语：「钱包」→「钱包地址已复制」。
  final String label;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: const Icon(Icons.copy_rounded, size: 13),
      color: AppColors.taupe,
      // 13px 的图标如果按 IconButton 默认的 48×48 见方，会把这一行撑高；
      // 这里压到 28×28：足够点得中（≥ 24 是可用的最小触控尺寸），又不会撑开行高。
      padding: EdgeInsets.zero,
      visualDensity: VisualDensity.compact,
      constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
      tooltip: '复制$label地址',
      onPressed: () => _copy(context),
    );
  }

  Future<void> _copy(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await Clipboard.setData(ClipboardData(text: value));
      messenger.showSnackBar(
        SnackBar(
          content: Text('$label地址已复制'),
          duration: const Duration(seconds: 2),
        ),
      );
    } on Object {
      messenger.showSnackBar(
        SnackBar(
          content: Text('$label地址复制失败，请长按手动选中复制'),
          duration: const Duration(seconds: 3),
        ),
      );
    }
  }
}
