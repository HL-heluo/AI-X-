import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/app.dart';
import 'package:flutter_application_1/core/network/api_exception.dart';
import 'package:flutter_application_1/core/storage/token_store.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/providers/app_providers.dart';

import 'shell_harness.dart';

const evidenceId = 'f274acca-d727-4a46-94cd-be18a7cf81ca';

class _MarketClient extends FakeApiClient {
  var public = true;
  var purchased = false;
  Object? purchaseBody;

  @override
  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    if (path == '/public/evidence/$evidenceId') {
      if (!public) throw AppException.fromResponse(httpStatus: 404);
      return {
        'evidence_id': evidenceId,
        'title': 'A shared work',
        'author_name': 'Public author',
        'description': 'Published description',
        'prompt': 'Public prompt',
        'sha256': List.filled(64, 'a').join(),
        'tx_id': List.filled(64, 'b').join(),
        'recorded_at': '2026-11-20T01:01:00Z',
        'channel': 'videochannel',
        'transfers': <Map<String, dynamic>>[],
      };
    }
    if (path == '/marketplace/listings') {
      return _page(
        purchased
            ? []
            : [
                {
                  'id': 1,
                  'price': 50,
                  'evidence_id': evidenceId,
                  'title': 'A shared work',
                  'author_name': 'Public author',
                  'seller_name': 'seller',
                  'is_seller': false,
                  'reserved': true,
                },
              ],
      );
    }
    if (path == '/marketplace/holdings') return _page([]);
    if (path == '/marketplace/trades') return _page(purchased ? [_trade] : []);
    return super.get(path, query: query);
  }

  Map<String, dynamic> _page(List<Map<String, dynamic>> items) => {
    'items': items,
    'page': 1,
    'page_size': 30,
    'total': items.length,
  };

  final _trade = {
    'trade_id': 'trade-1',
    'title': 'A shared work',
    'side': 'buy',
    'price': 50,
    'status': 'pending',
    'tx_id': null,
    'created_at': null,
  };

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body}) async {
    if (path == '/marketplace/listings/1/purchase') {
      purchaseBody = body;
      purchased = true;
      return _trade;
    }
    return super.post(path, body: body);
  }
}

void main() {
  testWidgets(
    'public deep link works without a session and handles revocation',
    (tester) async {
      final client = _MarketClient();
      tester.binding.platformDispatcher.defaultRouteNameTestValue =
          '/verify/$evidenceId';
      addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue,
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiClientProvider.overrideWithValue(client),
            tokenStoreProvider.overrideWithValue(InMemoryTokenStore()),
          ],
          child: const AiVideoApp(),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('A shared work'), findsOneWidget);
      expect(find.textContaining('Public prompt'), findsOneWidget);
      expect(find.text('Fabric 存证回执'), findsOneWidget);

      client.public = false;
      await tester.tap(find.text('查询'));
      await tester.pumpAndSettle();
      expect(find.text('未找到公开记录'), findsOneWidget);
      expect(find.textContaining('Public prompt'), findsNothing);
    },
  );

  testWidgets(
    'bottom trading tab supports purchase and shows a pending Fabric receipt',
    (tester) async {
      final client = _MarketClient();
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await pumpLoggedInShell(tester, apiClient: client);
      await tester.tap(find.byKey(const Key('tab.2')));
      await tester.pumpAndSettle();
      expect(find.text('作品交易中心'), findsOneWidget);
      expect(find.text('公开核验'), findsOneWidget);
      expect(
        tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
        2,
      );
      await tester.tap(find.widgetWithText(FilledButton, '购买'));
      await tester.pumpAndSettle();
      expect(find.textContaining('50 VCR'), findsWidgets);
      await tester.tap(find.widgetWithText(FilledButton, '确认购买'));
      await tester.pumpAndSettle();
      expect(client.purchaseBody, {'price': 50});
      expect(find.text('暂无可见挂单'), findsOneWidget);
      await tester.tap(find.text('成交记录'));
      await tester.pumpAndSettle();
      expect(find.text('买入 50 VCR · 待上链'), findsOneWidget);
      await tester.tap(find.byKey(const Key('tab.3')));
      await tester.pumpAndSettle();
      expect(find.text('个人中心'), findsOneWidget);
      await unmountAndDrain(tester);
    },
  );
}
