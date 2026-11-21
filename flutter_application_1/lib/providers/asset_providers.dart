import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/asset.dart';
import '../models/paged.dart';
import '../models/video_evidence.dart';
import 'app_providers.dart';

/// 作品列表的完整状态：已有的资产 + 还有没有下一页 + 正在不在拉下一页。
///
/// 【为什么这三样装在一个对象里】和 `CreditLedgerState` 完全同一个理由：
/// 翻页失败时若把 `hasMore` 翻成 false，用户会以为「我的作品就这么多了」；
/// 若在 `loadingMore` 为 true 时又点一次，同一页会被追加两遍。
/// 拆成三个 provider 的话，这三者的一致性要由每个调用点自己维护 ——
/// 那正是分页 bug 的标准产地。
class UserAssetsState {
  const UserAssetsState({
    this.assets = const [],
    this.hasMore = false,
    this.loadingMore = false,
  });

  /// 全部资产，**包含 `thumbnail`**。
  ///
  /// 【为什么不在这一层就把封面过滤掉】因为视频格子上要用的**正是**
  /// 那张封面图（它是独立的一条记录，见 §11.2）。过滤掉就没得用了。
  /// 需要「只要作品」的地方用 [works] 这个 getter。
  final List<Asset> assets;

  final bool hasMore;
  final bool loadingMore;

  /// 真正的作品（图片 + 视频），**不含封面**。
  ///
  /// 【为什么封面要排除】它是视频的附属文件，不是一件独立作品。
  /// 不过滤的话，一个视频会在网格里占两格（一格视频、一格它的封面图）。
  List<Asset> get works =>
      assets.where((a) => a.kind != AssetKind.thumbnail).toList(growable: false);

  /// 某个视频资产的封面地址。
  ///
  /// 【怎么配对】`thumbnail` 和它的 `video` 是同一个任务的产物
  /// （见 `FakeApiClient._createAssetsFor`），所以按 `task_id` 找。
  /// 找不到就返回 null —— 网格那边会退化成一个中性占位，
  /// **不要**退化成「直接加载视频文件当封面」（见 §9.3：列表只加载缩略图）。
  String? coverUrlOf(Asset asset) {
    if (!asset.isVideo) return null;
    final taskId = asset.taskId;
    if (taskId == null) return null;
    for (final a in assets) {
      if (a.kind == AssetKind.thumbnail && a.taskId == taskId) {
        return a.publicUrl;
      }
    }
    return null;
  }

  UserAssetsState copyWith({
    List<Asset>? assets,
    bool? hasMore,
    bool? loadingMore,
  }) {
    return UserAssetsState(
      assets: assets ?? this.assets,
      hasMore: hasMore ?? this.hasMore,
      loadingMore: loadingMore ?? this.loadingMore,
    );
  }
}

/// 我的作品（分页）
///
/// 【v1 只读，除了删除】这一版没有「编辑作品」这种事 ——
/// 产物是生成出来的，不是用户编辑的。留 [UserAssetsNotifier.delete] 是因为
/// 用户确实需要能删掉不想留的东西（§12.1 有 `DELETE /assets/{id}`）。
class UserAssetsNotifier extends AsyncNotifier<UserAssetsState> {
  UserAssetsNotifier({this.certifiedOnly = false});

  final bool certifiedOnly;
  /// 已经装进 state 的是第几页。
  ///
  /// 【为什么不从 `assets.length` 反推】因为每页给多少条是服务端定的，
  /// 最后一页就是不足的。反推出来的页码一旦偏了，用户会看到重复或跳过的作品。
  int _loadedPage = 1;

  /// 首页的「最近作品」读的是**同一个 provider**，只是自己取了前几条、
  /// 不翻页（见 `RecentWorksSection._maxItems`）。
  ///
  /// 【为什么不为首页单开一个 provider】那会变成「同一份数据的两个副本」：
  /// 在作品页删掉一张图，回到首页它还在 —— 这类不一致最难解释也最难查。

  @override
  Future<UserAssetsState> build() async {
    // 【为什么要 watch token】作品是**谁的**作品，取决于现在登录的是谁。
    // 不 watch 的话，A 登出、B 登录后 B 会在首页看到 A 的作品 ——
    // 那是最不该串的一种数据。
    final token = ref.watch(authTokenProvider);
    if (token == null) throw AppException.unauthorized();

    _loadedPage = 1;
    final first = await _fetch(1);
    return UserAssetsState(assets: first.items, hasMore: first.hasMore);
  }

  /// 加载下一页并**追加**。返回是否成功。
  Future<bool> loadMore() async {
    final current = state.value;
    // 三种情况都不该发请求：第一页还没落地 / 没有下一页 / 正在拉
    if (current == null || !current.hasMore || current.loadingMore) return true;

    state = AsyncData(current.copyWith(loadingMore: true));
    try {
      final next = await _fetch(_loadedPage + 1);
      _loadedPage += 1;
      state = AsyncData(
        UserAssetsState(
          assets: [...current.assets, ...next.items],
          hasMore: next.hasMore,
        ),
      );
      return true;
    } on Object {
      // 【为什么必须把 loadingMore 退回去】不退的话这个列表就永久卡死了：
      // 守卫看到 loadingMore 为 true 会拦掉后续每一次 loadMore。
      state = AsyncData(current.copyWith(loadingMore: false));
      return false;
    }
  }

  /// 从头重拉（下拉刷新）。翻过的页全部作废。
  Future<void> refresh() async {
    if (!state.hasValue) state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      _loadedPage = 1;
      final first = await _fetch(1);
      return UserAssetsState(assets: first.items, hasMore: first.hasMore);
    });
  }

  /// 删除一件作品。
  ///
  /// 【注意删的是资产不是任务】任务记录要留着 —— 它是积分流水的凭据。
  /// 用户把视频删了，但「这笔花了 24 积分」的记录必须还在，否则账没法对。
  /// 这一点在 `AssetRepository.delete` 的注释里也写了，两边口径必须一致。
  Future<void> delete(String assetId) async {
    await ref.read(assetRepositoryProvider).delete(assetId);
    // 【为什么不本地摘掉那一条就完事】因为一个视频连带它的封面是两条记录，
    // 本地摘掉容易漏。直接重拉一次，让服务端说了算。
    await refresh();
    ref.invalidate(certifiedAssetsProvider);
  }

  Future<Paged<Asset>> _fetch(int page) =>
      ref.read(assetRepositoryProvider).fetchAssets(page: page, certifiedOnly: certifiedOnly);
}

final certifiedAssetsProvider =
    AsyncNotifierProvider.autoDispose<UserAssetsNotifier, UserAssetsState>(
      () => UserAssetsNotifier(certifiedOnly: true),
      retry: noAutoRetry,
    );

final videoEvidenceProvider = FutureProvider.autoDispose.family<VideoEvidence, String>(
  (ref, assetId) async {
    if (ref.watch(authTokenProvider) == null) throw AppException.unauthorized();
    final receipt = await ref.watch(assetRepositoryProvider).fetchEvidence(assetId);
    if (ref.mounted && receipt.isWaiting) {
      final timer = Timer(const Duration(seconds: 3), ref.invalidateSelf);
      ref.onDispose(timer.cancel);
    }
    return receipt;
  },
  retry: noAutoRetry,
);

final userAssetsProvider =
    AsyncNotifierProvider<UserAssetsNotifier, UserAssetsState>(
      UserAssetsNotifier.new,
      // 见 `noAutoRetry` 的注释：默认的自动重试会让「加载更多」变得不可预期
      retry: noAutoRetry,
    );

/// 某个任务的产物
///
/// ─────────────────────────────────────────────────────────
/// 【为什么需要它】结果页要显示「这个任务生成出来的那张图 / 那个视频」，
/// 而任务详情接口**不返回产物** —— 产物是 `assets` 表里独立的一行
/// （§11.2）。两边只能靠 `task_id` 关联。
///
/// 【为什么不在客户端把整个作品列表拉下来筛】
/// 因为作品会越攒越多。现在只有几条的时候筛一下没事，等用户有 200 张图时，
/// 为了看一个结果要下 200 条记录。所以**在请求上就带上筛选条件**。
///
/// 【⚠️ 契约补充】§12.1 的 `GET /assets` 只写了分页参数，没有 `task_id`。
/// 这里按最自然的方式拍板冻结为查询参数：
///   `GET /assets?task_id=<id>`
/// 和 `GET /generation/cost` 的 kind/duration/ratio 是同一类处理
/// （见 `api_paths.dart` 里 `generationCost` 的注释）。
/// **Mock 先按这个实现，接真后端前需与后端确认一次。**
/// ─────────────────────────────────────────────────────────
class TaskAssetQuery {
  const TaskAssetQuery({required this.taskId, this.preferKind});

  final String taskId;

  /// 想要哪种产物。
  ///
  /// 【为什么需要它】一个视频任务会产出**两条**记录：视频本体和它的封面。
  /// 结果页要的是视频本体，不能拿错了 —— 拿成封面的话，
  /// 用户会看到一个「能播的封面」这种莫名其妙的东西。
  final AssetKind? preferKind;

  @override
  bool operator ==(Object other) =>
      other is TaskAssetQuery &&
      other.taskId == taskId &&
      other.preferKind == preferKind;

  @override
  int get hashCode => Object.hash(taskId, preferKind);
}

/// 按任务取产物。取不到返回 null（任务还在跑，或者失败了没有产物）。
final taskAssetProvider =
    FutureProvider.autoDispose.family<Asset?, TaskAssetQuery>((ref, query) async {
  final token = ref.watch(authTokenProvider);
  if (token == null) throw AppException.unauthorized();

  final paged = await ref
      .read(assetRepositoryProvider)
      .fetchAssets(taskId: query.taskId, pageSize: 10);

  if (paged.items.isEmpty) return null;

  // 优先挑请求的那一种；没有就退回第一条（总比什么都不显示好）
  for (final a in paged.items) {
    if (query.preferKind == null || a.kind == query.preferKind) return a;
  }
  return paged.items.first;
}, retry: noAutoRetry);
