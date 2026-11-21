import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/chain_summary.dart';
import '../models/credit_ledger_entry.dart';
import '../models/paged.dart';
import 'app_providers.dart';

/// 积分流水列表的完整状态：已有的条目 + 还有没有下一页 + 正在不在拉下一页。
///
/// 【为什么这三样必须装在一个类里】
/// 它们任何一个单独变化都会让界面说谎：
/// 翻页失败时若把 `hasMore` 翻成 false，用户会以为「流水就这么多了」；
/// 若在 `loadingMore` 为 true 时又点一次，同一页会被追加两遍。
/// 拆成三个 provider 的话，这三者之间的一致性得由每个调用点自己维护 ——
/// 那正是分页 bug 的标准产地。放进一个不可变对象里，改就是一起改。
class CreditLedgerState {
  const CreditLedgerState({
    this.entries = const [],
    this.hasMore = false,
    this.loadingMore = false,
  });

  final List<CreditLedgerEntry> entries;
  final bool hasMore;
  final bool loadingMore;

  CreditLedgerState copyWith({
    List<CreditLedgerEntry>? entries,
    bool? hasMore,
    bool? loadingMore,
  }) {
    return CreditLedgerState(
      entries: entries ?? this.entries,
      hasMore: hasMore ?? this.hasMore,
      loadingMore: loadingMore ?? this.loadingMore,
    );
  }
}

/// 积分流水（分页）。
///
/// 【v1 只读】没有充值入口 —— §7.6 的充值档位是 v3 预留。
/// 这里**故意不提供任何写入方法**，页面也就无从添加一个「充值」按钮。
class CreditLedgerNotifier extends AsyncNotifier<CreditLedgerState> {
  /// 已经装进 [CreditLedgerState.entries] 的是第几页。
  ///
  /// 【为什么放在 notifier 的字段里，而不是从 entries.length 反推页码】
  /// entries 的长度取决于服务端每页给多少条，客户端**不能**假设它等于 pageSize
  /// （服务端最后一页就是不足的，将来也可能改每页条数）。
  /// 反推出来的页码一旦偏了，用户就会看到重复或跳过的流水。
  int _loadedPage = 1;

  @override
  Future<CreditLedgerState> build() async {
    // 【为什么要 watch token】和 `MeProfileNotifier.build` 同一个理由：
    // 账本是**谁的**账本，取决于现在登录的是谁。A 登出、B 登录后
    // 这里的缓存必须作废，否则 B 会看到 A 的流水 —— 那是最不该串的一种数据。
    final token = ref.watch(authTokenProvider);
    if (token == null) throw AppException.unauthorized();

    _loadedPage = 1;
    final first = await _fetch(1);
    return CreditLedgerState(entries: first.items, hasMore: first.hasMore);
  }

  /// 加载下一页并**追加**到列表末尾。
  ///
  /// 返回是否成功 —— 失败时页面给一句提示，但**已经拉到的流水必须留在屏幕上**。
  /// 因为「下一页没拉到」不该惩罚用户把「这一页也别看了」。
  Future<bool> loadMore() async {
    final current = state.value;
    // 三种情况都不该发请求：第一页还没落地 / 没有下一页 / 正在拉。
    // 最后一个尤其重要 —— 它挡的是用户连点两下「加载更多」时的重复请求。
    if (current == null || !current.hasMore || current.loadingMore) return true;

    state = AsyncData(current.copyWith(loadingMore: true));
    try {
      final next = await _fetch(_loadedPage + 1);
      _loadedPage += 1;
      state = AsyncData(
        CreditLedgerState(
          entries: [...current.entries, ...next.items],
          hasMore: next.hasMore,
        ),
      );
      return true;
    } on Object {
      // 【为什么把 loadingMore 退回 false】
      // 不退的话这个列表就**永久卡死**了：守卫看到 loadingMore 为 true
      // 会拦掉后续每一次 loadMore，用户再也翻不动页。
      // 失败是可重试的，卡死不是。
      state = AsyncData(current.copyWith(loadingMore: false));
      return false;
    }
  }

  /// 从头重拉（下拉刷新）。翻过的页全部作废 —— 用户想要的是最新的账。
  Future<void> refresh() async {
    if (!state.hasValue) state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      _loadedPage = 1;
      final first = await _fetch(1);
      return CreditLedgerState(entries: first.items, hasMore: first.hasMore);
    });
  }

  Future<Paged<CreditLedgerEntry>> _fetch(int page) =>
      ref.read(creditRepositoryProvider).fetchLedger(page: page);
}

/// 影子链凭证（`GET /credits/chain`）。
///
/// 【为什么单独一个 provider】它和流水是两条数据源：流水是账本，
/// 链上凭证是「链上到底有没有这笔钱」。拆开之后任一侧失败只影响自己那半。
final chainSummaryProvider = FutureProvider.autoDispose<ChainSummary>((ref) async {
  final token = ref.watch(authTokenProvider);
  if (token == null) throw AppException.unauthorized();
  return ref.watch(creditRepositoryProvider).fetchChainSummary();
});

final creditLedgerProvider =
    AsyncNotifierProvider<CreditLedgerNotifier, CreditLedgerState>(
      CreditLedgerNotifier.new,
      // 见 `noAutoRetry` 的注释：默认的自动重试会让「加载更多」和刷新变得不可预期
      retry: noAutoRetry,
    );
