import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/json_utils.dart';
import '../../core/network/api_client.dart';
import '../../models/paged.dart';
import '../../providers/app_providers.dart';

final workMarketplaceProvider = Provider<WorkMarketplaceRepository>(
  (ref) => WorkMarketplaceRepository(ref.watch(apiClientProvider)),
);
final marketWorkProvider = FutureProvider.autoDispose
    .family<MarketWork, String>(
      (ref, assetId) => ref.watch(workMarketplaceProvider).work(assetId),
      retry: noAutoRetry,
    );

extension on Map<String, dynamic> {
  String requireString(Object? value, {required String field}) {
    if (value is String) return value;
    throw FormatException('缺少字段 $field');
  }
}

class WorkMarketplaceRepository {
  WorkMarketplaceRepository(this._client);

  final ApiClient _client;

  String _publication(String assetId) => '/assets/$assetId/publication';

  Future<WorkPublication> publication(String assetId) async =>
      WorkPublication.fromJson(await _client.get(_publication(assetId)));

  Future<void> publish(String assetId, WorkPublication publication) async {
    await _client.post(
      _publication(assetId),
      body: {
        'title': publication.title,
        'author_name': publication.authorName,
        'description': publication.description,
        'show_prompt': publication.showPrompt,
      },
    );
  }

  Future<void> revoke(String assetId) async {
    await _client.delete(_publication(assetId));
  }

  Future<PublicWorkProof> verify(String evidenceId) async =>
      PublicWorkProof.fromJson(
        await _client.get(
          '/public/evidence/${Uri.encodeComponent(evidenceId)}',
        ),
      );

  Future<MarketWork> work(String assetId) async =>
      MarketWork.fromJson(await _client.get('/marketplace/works/$assetId'));

  Future<Paged<MarketListing>> listings(int page) async => Paged.fromJson(
    await _client.get('/marketplace/listings', query: {'page': page}),
    MarketListing.fromJson,
  );

  Future<Paged<MarketWork>> holdings(int page) async => Paged.fromJson(
    await _client.get('/marketplace/holdings', query: {'page': page}),
    MarketWork.fromJson,
  );

  Future<Paged<MarketTrade>> trades(int page) async => Paged.fromJson(
    await _client.get('/marketplace/trades', query: {'page': page}),
    MarketTrade.fromJson,
  );

  Future<void> list(String assetId, int price, String? buyer) async {
    await _client.post(
      '/marketplace/listings',
      body: {
        'asset_id': int.parse(assetId),
        'price': price,
        'buyer_username': buyer,
      },
    );
  }

  Future<void> cancel(int listingId) async {
    await _client.delete('/marketplace/listings/$listingId');
  }

  Future<MarketTrade> purchase(MarketListing listing) async =>
      MarketTrade.fromJson(
        await _client.post(
          '/marketplace/listings/${listing.id}/purchase',
          body: {'price': listing.price},
        ),
      );

  Future<String> downloadPath(String assetId) async {
    final result = await _client.post(
      '/marketplace/works/$assetId/download-link',
    );
    return result.requireString(result['path'], field: 'path');
  }
}

class WorkPublication {
  const WorkPublication({
    required this.visible,
    required this.title,
    required this.authorName,
    required this.description,
    required this.showPrompt,
  });

  factory WorkPublication.fromJson(
    Map<String, dynamic> json,
  ) => WorkPublication(
    visible: json['visible'] == true,
    title: json.requireString(json['title'], field: 'title'),
    authorName: json.requireString(json['author_name'], field: 'author_name'),
    description: json.requireString(json['description'], field: 'description'),
    showPrompt: json['show_prompt'] == true,
  );

  final bool visible;
  final String title;
  final String authorName;
  final String description;
  final bool showPrompt;
}

class PublicWorkProof {
  PublicWorkProof.fromJson(Map<String, dynamic> json)
    : evidenceId = json.requireString(
        json['evidence_id'],
        field: 'evidence_id',
      ),
      title = json.requireString(json['title'], field: 'title'),
      authorName = json.requireString(
        json['author_name'],
        field: 'author_name',
      ),
      description = json.requireString(
        json['description'],
        field: 'description',
      ),
      prompt = json.asStringOrNull(json['prompt']),
      txId = json.requireString(json['tx_id'], field: 'tx_id'),
      sha256 = json.requireString(json['sha256'], field: 'sha256'),
      channel = json.requireString(json['channel'], field: 'channel'),
      recordedAt = json.asDateTimeOrNull(json['recorded_at']),
      transfers = json
          .asJsonList(json['transfers'], field: 'transfers')
          .map(PublicWorkTransfer.fromJson)
          .toList(growable: false);

  final String evidenceId,
      title,
      authorName,
      description,
      txId,
      sha256,
      channel;
  final String? prompt;
  final DateTime? recordedAt;
  final List<PublicWorkTransfer> transfers;
}

class PublicWorkTransfer {
  PublicWorkTransfer.fromJson(Map<String, dynamic> json)
    : tradeId = json.requireString(json['trade_id'], field: 'trade_id'),
      txId = json.requireString(json['tx_id'], field: 'tx_id'),
      recordedAt = json.asDateTimeOrNull(json['recorded_at']);

  final String tradeId, txId;
  final DateTime? recordedAt;
}

class MarketWork {
  MarketWork.fromJson(Map<String, dynamic> json)
    : assetId = json.requireInt(json['asset_id'], field: 'asset_id').toString(),
      evidenceId = json.requireString(
        json['evidence_id'],
        field: 'evidence_id',
      ),
      title = json.requireString(json['title'], field: 'title'),
      authorName = json.requireString(
        json['author_name'],
        field: 'author_name',
      ),
      holderName = json.asStringOrNull(json['holder_name']),
      isHolder = json['is_holder'] == true,
      activeListingId = json.asIntOrNull(
        json['active_listing_id'],
        field: 'active_listing_id',
      );

  final String assetId, evidenceId, title, authorName;
  final String? holderName;
  final bool isHolder;
  final int? activeListingId;
}

class MarketListing {
  MarketListing.fromJson(Map<String, dynamic> json)
    : id = json.requireInt(json['id'], field: 'id'),
      price = json.requireInt(json['price'], field: 'price'),
      evidenceId = json.requireString(
        json['evidence_id'],
        field: 'evidence_id',
      ),
      title = json.requireString(json['title'], field: 'title'),
      authorName = json.requireString(
        json['author_name'],
        field: 'author_name',
      ),
      sellerName = json.requireString(
        json['seller_name'],
        field: 'seller_name',
      ),
      isSeller = json['is_seller'] == true,
      reserved = json['reserved'] == true;

  final int id, price;
  final String evidenceId, title, authorName, sellerName;
  final bool isSeller, reserved;
}

class MarketTrade {
  MarketTrade.fromJson(Map<String, dynamic> json)
    : tradeId = json.requireString(json['trade_id'], field: 'trade_id'),
      title = json.requireString(json['title'], field: 'title'),
      side = json.requireString(json['side'], field: 'side'),
      price = json.requireInt(json['price'], field: 'price'),
      status = json.requireString(json['status'], field: 'status'),
      txId = json.asStringOrNull(json['tx_id']),
      createdAt = json.asDateTimeOrNull(json['created_at']);

  final String tradeId, title, side, status;
  final int price;
  final String? txId;
  final DateTime? createdAt;

  String get statusLabel => switch (status) {
    'committed' => '已上链',
    'submitted' => '确认中',
    'failed' => '上链失败',
    'conflict' => '待核查',
    _ => '待上链',
  };
}
