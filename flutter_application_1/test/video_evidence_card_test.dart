import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/models/video_evidence.dart';
import 'package:flutter_application_1/pages/generate/widgets/video_evidence_card.dart';
import 'package:flutter_application_1/providers/asset_providers.dart';

void main() {
  testWidgets('confirmed video shows the receipt and copy controls', (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        videoEvidenceProvider('7').overrideWith((ref) async => const VideoEvidence(
          status: 'committed', evidenceId: 'video-7', sha256: 'demo-digest', txId: 'demo-tx',
        )),
      ],
      child: const MaterialApp(home: Scaffold(body: VideoEvidenceCard(assetId: '7'))),
    ));
    await tester.pumpAndSettle();

    expect(find.text('视频存证 · 已存证'), findsOneWidget);
    expect(find.text('video-7'), findsOneWidget);
    expect(find.text('demo-digest'), findsOneWidget);
    expect(find.byTooltip('复制 Fabric 交易 ID'), findsOneWidget);
  });
}
