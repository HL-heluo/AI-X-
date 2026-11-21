import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format/date_format.dart';
import '../../core/network/api_exception.dart';
import '../../data/remote/work_marketplace_repository.dart';
import '../../models/paged.dart';
import '../../providers/app_providers.dart';
import '../../providers/credit_providers.dart';
import '../../providers/me_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/glass_card.dart';
import 'work_download.dart';

String _marketError(AppException error) {
  if (error.httpStatus == 400 ||
      error.httpStatus == 404 ||
      error.httpStatus == 409) {
    return error.message;
  }
  return error.userMessage;
}

void _notice(BuildContext context, String message) =>
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));

class MarketplacePage extends ConsumerWidget {
  const MarketplacePage({super.key, required this.active});

  final bool active;

  Future<void> _buy(
    BuildContext context,
    WidgetRef ref,
    MarketListing listing,
    VoidCallback reload,
  ) async {
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('确认购买'),
        content: Text(
          '用 ${listing.price} VCR 购买「${listing.title}」。成交后可以下载原片及再次转让。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认购买'),
          ),
        ],
      ),
    );
    if (approved != true || !context.mounted) return;
    try {
      await ref.read(workMarketplaceProvider).purchase(listing);
      if (!context.mounted) return;
      ref.invalidate(meProfileProvider);
      ref.invalidate(chainSummaryProvider);
      ref.invalidate(creditLedgerProvider);
      reload();
      _notice(context, '成交成功，可在「我的持有」下载或上架');
    } on AppException catch (error) {
      if (context.mounted) {
        reload();
        _notice(context, _marketError(error));
      }
    }
  }

  Future<void> _cancel(
    BuildContext context,
    WidgetRef ref,
    MarketListing listing,
    VoidCallback reload,
  ) async {
    try {
      await ref.read(workMarketplaceProvider).cancel(listing.id);
      if (context.mounted) reload();
    } on AppException catch (error) {
      if (context.mounted) _notice(context, _marketError(error));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(
          automaticallyImplyLeading: false,
          centerTitle: false,
          titleSpacing: 20,
          toolbarHeight: 66,
          title: const Text('作品交易中心'),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: OutlinedButton.icon(
                onPressed: () =>
                    Navigator.of(context).pushNamed<void>(AppRoutes.verify),
                icon: const Icon(Icons.verified_outlined, size: 18),
                label: const Text('公开核验'),
              ),
            ),
          ],
          bottom: const TabBar(
            tabs: [
              Tab(text: '挂单'),
              Tab(text: '我的持有'),
              Tab(text: '成交记录'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _MarketList<MarketListing>(
              active: active,
              empty: '暂无可见挂单',
              load: (repo, page) => repo.listings(page),
              item: (context, item, reload) => GlassCard(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const _MarketIcon(Icons.movie_outlined),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                item.title,
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '作者 ${item.authorName} · 卖家 ${item.sellerName}',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    DecoratedBox(
                      decoration: BoxDecoration(
                        color: AppColors.bgCream,
                        borderRadius: BorderRadius.circular(AppRadius.lg),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 5,
                        ),
                        child: Text(
                          '${item.price} VCR${item.reserved ? ' · 指定买家' : ''}',
                          style: const TextStyle(
                            color: AppColors.gold,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        item.isSeller
                            ? OutlinedButton(
                                onPressed: () =>
                                    _cancel(context, ref, item, reload),
                                child: const Text('撤单'),
                              )
                            : FilledButton(
                                onPressed: () =>
                                    _buy(context, ref, item, reload),
                                child: const Text('购买'),
                              ),
                        TextButton(
                          onPressed: () => Navigator.of(context)
                              .pushNamed<void>(
                                AppRoutes.verification(item.evidenceId),
                              ),
                          child: const Text('查询公开存证'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            _MarketList<MarketWork>(
              active: active,
              empty: '暂无已存证的持有作品',
              load: (repo, page) => repo.holdings(page),
              item: (context, item, reload) => GlassCard(
                child: Material(
                  type: MaterialType.transparency,
                  child: ListTile(
                    leading: const _MarketIcon(Icons.video_library_outlined),
                    title: Text(item.title),
                    subtitle: Text('作者 ${item.authorName}'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () async {
                      await Navigator.of(context)
                          .push<void>(AppRoutes.workRoute(item.assetId));
                      if (context.mounted) reload();
                    },
                  ),
                ),
              ),
            ),
            _MarketList<MarketTrade>(
              active: active,
              empty: '暂无成交记录',
              load: (repo, page) => repo.trades(page),
              item: (context, item, _) => GlassCard(
                child: Material(
                  type: MaterialType.transparency,
                  child: ExpansionTile(
                    leading: _MarketIcon(
                      item.side == 'buy' ? Icons.south_west : Icons.north_east,
                    ),
                    title: Text(item.title),
                    subtitle: Text(
                      '${item.side == 'buy' ? '买入' : '售出'} ${item.price} VCR · ${item.statusLabel}',
                    ),
                    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                    children: [
                      SelectableText('成交编号 ${item.tradeId}'),
                      Text(formatDate(item.createdAt)),
                      if (item.status == 'committed' && item.txId != null)
                        SelectableText('Fabric 交易 ID ${item.txId}'),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MarketIcon extends StatelessWidget {
  const _MarketIcon(this.icon);

  final IconData icon;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: const BoxDecoration(
      color: AppColors.sageTint,
      borderRadius: BorderRadius.all(Radius.circular(AppRadius.lg)),
    ),
    child: Padding(
      padding: const EdgeInsets.all(11),
      child: Icon(icon, color: AppColors.sage, size: 22),
    ),
  );
}

class _MarketList<T> extends ConsumerStatefulWidget {
  const _MarketList({
    required this.active,
    required this.empty,
    required this.load,
    required this.item,
  });

  final bool active;
  final String empty;
  final Future<Paged<T>> Function(WorkMarketplaceRepository, int) load;
  final Widget Function(BuildContext, T, VoidCallback) item;

  @override
  ConsumerState<_MarketList<T>> createState() => _MarketListState<T>();
}

class _MarketListState<T> extends ConsumerState<_MarketList<T>> {
  int _page = 1;
  Future<Paged<T>>? _future;

  @override
  void initState() {
    super.initState();
    if (widget.active) {
      _future = widget.load(ref.read(workMarketplaceProvider), _page);
    }
  }

  @override
  void didUpdateWidget(covariant _MarketList<T> oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) {
      _future = widget.load(ref.read(workMarketplaceProvider), _page);
    }
  }

  void _load(int page) {
    if (!mounted) return;
    setState(() {
      _page = page;
      _future = widget.load(ref.read(workMarketplaceProvider), _page)..ignore();
    });
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Paged<T>>(
    future: _future,
    builder: (context, snapshot) {
      if (_future == null) return const SizedBox.shrink();
      if (snapshot.connectionState != ConnectionState.done) {
        return const Center(child: CircularProgressIndicator());
      }
      if (snapshot.hasError) {
        final error = snapshot.error;
        return Center(
          child: TextButton(
            onPressed: () => _load(_page),
            child: Text(
              error is AppException
                  ? '${_marketError(error)} · 重试'
                  : '加载失败 · 重试',
            ),
          ),
        );
      }
      final data = snapshot.requireData;
      return Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 740),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Align(
                alignment: Alignment.centerRight,
                child: IconButton(
                  tooltip: '刷新',
                  onPressed: () => _load(_page),
                  icon: const Icon(Icons.refresh),
                ),
              ),
              if (data.items.isEmpty)
                GlassCard(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 36,
                  ),
                  child: Column(
                    children: [
                      const _MarketIcon(Icons.inventory_2_outlined),
                      const SizedBox(height: 12),
                      Text(widget.empty, textAlign: TextAlign.center),
                    ],
                  ),
                ),
              for (final item in data.items)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: widget.item(context, item, () => _load(_page)),
                ),
              if (_page > 1 || _page * data.pageSize < data.total)
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    TextButton(
                      onPressed: _page > 1 ? () => _load(_page - 1) : null,
                      child: const Text('上一页'),
                    ),
                    Text('第 $_page 页'),
                    TextButton(
                      onPressed: _page * data.pageSize < data.total
                          ? () => _load(_page + 1)
                          : null,
                      child: const Text('下一页'),
                    ),
                  ],
                ),
            ],
          ),
        ),
      );
    },
  );
}

class MarketWorkPage extends ConsumerStatefulWidget {
  const MarketWorkPage({super.key, required this.assetId});

  final String assetId;

  @override
  ConsumerState<MarketWorkPage> createState() => _MarketWorkPageState();
}

class _MarketWorkPageState extends ConsumerState<MarketWorkPage> {
  final _price = TextEditingController();
  final _buyer = TextEditingController();
  late Future<MarketWork> _future;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _future = ref.read(workMarketplaceProvider).work(widget.assetId);
  }

  @override
  void dispose() {
    _price.dispose();
    _buyer.dispose();
    super.dispose();
  }

  Future<void> _action(
    Future<void> Function(WorkMarketplaceRepository) action,
  ) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action(ref.read(workMarketplaceProvider));
    } on AppException catch (error) {
      if (mounted) _notice(context, _marketError(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _reload() => setState(
    () =>
        _future = ref.read(workMarketplaceProvider).work(widget.assetId)
          ..ignore(),
  );

  Future<void> _list() async {
    final price = int.tryParse(_price.text.trim());
    if (price == null || price < 1 || price > 1000000000) {
      _notice(context, '请填写有效的整数积分价格');
      return;
    }
    await _action((repo) async {
      final buyer = _buyer.text.trim();
      await repo.list(widget.assetId, price, buyer.isEmpty ? null : buyer);
      if (mounted) _reload();
    });
  }

  Future<void> _download(WorkMarketplaceRepository repo) async {
    final base = ref.read(appConfigProvider).baseUrl;
    final link = Uri.parse(base)
        .resolve(await repo.downloadPath(widget.assetId));
    if (startWorkDownload(link)) return;
    await Clipboard.setData(ClipboardData(text: link.toString()));
    if (mounted) _notice(context, '已复制下载链接，请在两分钟内用浏览器打开');
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('作品交易')),
    body: FutureBuilder<MarketWork>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          final error = snapshot.error;
          return Center(
            child: TextButton(
              onPressed: _reload,
              child: Text(
                error is AppException
                    ? '${_marketError(error)} · 重试'
                    : '加载失败 · 重试',
              ),
            ),
          );
        }
        final work = snapshot.requireData;
        return Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                GlassCard(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const _MarketIcon(Icons.movie_outlined),
                      const SizedBox(height: 10),
                      Text(
                        work.title,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 8),
                      Text('原始作者 ${work.authorName}'),
                      Text('当前持有人 ${work.holderName ?? '未知'}'),
                    ],
                  ),
                ),
                if (work.isHolder) ...[
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    icon: const Icon(Icons.download_outlined),
                    onPressed: _busy ? null : () => _action(_download),
                    label: const Text('下载原片'),
                  ),
                  const SizedBox(height: 14),
                  if (work.activeListingId case final id?)
                    FilledButton(
                      onPressed: _busy
                          ? null
                          : () => _action((repo) async {
                              await repo.cancel(id);
                              if (mounted) _reload();
                            }),
                      child: const Text('撤销挂单'),
                    )
                  else ...[
                    TextField(
                      controller: _price,
                      keyboardType: TextInputType.number,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      decoration: const InputDecoration(labelText: '成交价格（VCR）'),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _buyer,
                      maxLength: 32,
                      decoration: const InputDecoration(
                        labelText: '指定买家用户名（选填）',
                      ),
                    ),
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _busy ? null : _list,
                      child: const Text('上架作品'),
                    ),
                  ],
                ],
              ],
            ),
          ),
        );
      },
    ),
  );
}
