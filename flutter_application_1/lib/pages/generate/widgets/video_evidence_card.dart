import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format/date_format.dart';
import '../../../data/remote/work_marketplace_repository.dart';
import '../../../providers/asset_providers.dart';
import '../../../router/app_router.dart';
import '../../../theme/app_theme.dart';
import '../../../widgets/glass_card.dart';
import '../../marketplace/publication_page.dart';

class VideoEvidenceCard extends ConsumerWidget {
  const VideoEvidenceCard({super.key, required this.assetId});

  final String assetId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = videoEvidenceProvider(assetId);
    final result = ref.watch(provider);
    final evidence = result.value;
    final work = evidence?.status == 'committed'
        ? ref.watch(marketWorkProvider(assetId)).value
        : null;
    if (evidence?.status == 'disabled') return const SizedBox.shrink();

    final status = switch (evidence?.status) {
      'pending' => '待存证',
      'submitted' => 'Fabric 确认中',
      'committed' => '已存证',
      'failed' => '存证失败',
      'conflict' => '待核查',
      'not_recorded' => '尚未登记',
      _ => result.hasError ? '暂时无法读取' : '正在读取',
    };
    return GlassCard(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.verified_outlined, color: AppColors.sage, size: 18),
              const SizedBox(width: 8),
              Expanded(child: Text('视频存证 · $status')),
              IconButton(
                tooltip: '刷新存证',
                onPressed: () {
                  ref.invalidate(provider);
                  ref.invalidate(marketWorkProvider(assetId));
                },
                icon: const Icon(Icons.refresh, size: 19),
              ),
            ],
          ),
          if (evidence?.recordedAt case final time?)
            Text('Fabric ${evidence?.channel ?? ''} · ${formatRelativeTime(time)}'),
          if (evidence?.evidenceId case final id?) _CopyValue(label: '存证编号', value: id),
          if (evidence?.sha256 case final digest?) _CopyValue(label: 'SHA-256', value: digest),
          if (evidence?.txId case final txId?) _CopyValue(label: 'Fabric 交易 ID', value: txId),
          if (work != null)
            Text('原始作者 ${work.authorName} · 当前持有人 ${work.holderName ?? '未知'}'),
          if (evidence?.status == 'committed' && evidence?.evidenceId != null)
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton(
                  onPressed: () => Navigator.of(context).push<void>(MaterialPageRoute(
                    builder: (_) => PublicationPage(assetId: assetId, evidenceId: evidence!.evidenceId!),
                  )),
                  child: const Text('公开存证'),
                ),
                TextButton(
                  onPressed: () => Navigator.of(context).push<void>(AppRoutes.workRoute(assetId)),
                  child: const Text('作品交易'),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

class _CopyValue extends StatelessWidget {
  const _CopyValue({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: Theme.of(context).textTheme.labelMedium),
              Text(value, maxLines: 1, overflow: TextOverflow.ellipsis),
            ],
          ),
        ),
        IconButton(
          tooltip: '复制 $label',
          icon: const Icon(Icons.copy_outlined, size: 17),
          onPressed: () async {
            var message = '已复制 $label';
            try {
              await Clipboard.setData(ClipboardData(text: value));
            } on PlatformException {
              message = '复制失败';
            }
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
            }
          },
        ),
      ],
    );
  }
}
