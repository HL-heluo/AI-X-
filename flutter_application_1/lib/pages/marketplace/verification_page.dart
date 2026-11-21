import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format/date_format.dart';
import '../../core/network/api_exception.dart';
import '../../data/remote/work_marketplace_repository.dart';
import '../../theme/app_theme.dart';
import '../../widgets/glass_card.dart';

class VerificationPage extends ConsumerStatefulWidget {
  const VerificationPage({super.key, this.evidenceId});

  final String? evidenceId;

  @override
  ConsumerState<VerificationPage> createState() => _VerificationPageState();
}

class _VerificationPageState extends ConsumerState<VerificationPage> {
  late final TextEditingController _id;
  PublicWorkProof? _proof;
  String? _error;
  int _request = 0;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _id = TextEditingController(text: widget.evidenceId);
    if (widget.evidenceId != null) _search();
  }

  @override
  void dispose() {
    _id.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    final id = _id.text.trim();
    if (id.isEmpty) return;
    final request = ++_request;
    setState(() {
      _proof = null;
      _error = null;
      _loading = true;
    });
    try {
      final proof = await ref.read(workMarketplaceProvider).verify(id);
      if (mounted && request == _request) setState(() => _proof = proof);
    } catch (error) {
      if (mounted && request == _request) {
        setState(
          () => _error = error is AppException && error.httpStatus == 404
              ? '未找到公开记录'
              : '暂时无法查询，请稍后重试',
        );
      }
    } finally {
      if (mounted && request == _request) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final evidenceField = TextField(
      controller: _id,
      decoration: const InputDecoration(
        labelText: '存证编号',
        prefixIcon: Icon(Icons.fingerprint),
      ),
      textInputAction: TextInputAction.search,
      onSubmitted: (_) => _search(),
    );
    final searchButton = FilledButton.icon(
      onPressed: _loading ? null : _search,
      icon: const Icon(Icons.search, size: 19),
      label: const Text('查询'),
    );
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(title: const Text('公开存证核验')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              GlassCard(
                padding: const EdgeInsets.all(18),
                child: LayoutBuilder(
                  builder: (context, constraints) => constraints.maxWidth >= 460
                      ? Row(
                          children: [
                            Expanded(child: evidenceField),
                            const SizedBox(width: 12),
                            SizedBox(
                              width: 112,
                              height: 48,
                              child: searchButton,
                            ),
                          ],
                        )
                      : Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            evidenceField,
                            const SizedBox(height: 12),
                            SizedBox(height: 44, child: searchButton),
                          ],
                        ),
                ),
              ),
              const SizedBox(height: 16),
              if (_loading) const Center(child: CircularProgressIndicator()),
              if (_error case final message?)
                GlassCard(
                  padding: const EdgeInsets.all(18),
                  child: Row(
                    children: [
                      const Icon(Icons.info_outline, color: AppColors.taupe),
                      const SizedBox(width: 10),
                      Expanded(child: Text(message)),
                    ],
                  ),
                ),
              if (_proof case final proof?) _ProofDetails(proof: proof),
            ],
          ),
        ),
      ),
    );
  }
}

class _ProofDetails extends StatelessWidget {
  const _ProofDetails({required this.proof});

  final PublicWorkProof proof;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        GlassCard(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(proof.title, style: theme.textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text('作者 ${proof.authorName}'),
              if (proof.description.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(proof.description),
              ],
              if (proof.prompt case final prompt?)
                _ProofField(label: '作者公开的提示词', value: prompt),
            ],
          ),
        ),
        const SizedBox(height: 12),
        GlassCard(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.verified_outlined,
                    color: AppColors.sage,
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Fabric 存证回执',
                      style: theme.textTheme.titleMedium,
                    ),
                  ),
                ],
              ),
              _ProofField(label: '存证编号', value: proof.evidenceId),
              _ProofField(label: '登记时间', value: formatDate(proof.recordedAt)),
              _ProofField(label: '通道', value: proof.channel),
              _ProofField(label: 'SHA-256', value: proof.sha256),
              _ProofField(label: 'Fabric 交易 ID', value: proof.txId),
            ],
          ),
        ),
        if (proof.transfers.isNotEmpty) ...[
          const SizedBox(height: 12),
          GlassCard(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('已确认的转让', style: theme.textTheme.titleMedium),
                for (final transfer in proof.transfers) ...[
                  _ProofField(label: '成交编号', value: transfer.tradeId),
                  Text(formatDate(transfer.recordedAt)),
                  _ProofField(label: 'Fabric 交易 ID', value: transfer.txId),
                ],
              ],
            ),
          ),
        ],
      ],
    );
  }
}

class _ProofField extends StatelessWidget {
  const _ProofField({required this.label, required this.value});

  final String label, value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 8),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: Theme.of(context).textTheme.bodySmall),
              SelectableText(value),
            ],
          ),
        ),
        IconButton(
          tooltip: '复制$label',
          onPressed: () => Clipboard.setData(ClipboardData(text: value)),
          icon: const Icon(Icons.copy_outlined, size: 18),
        ),
      ],
    ),
  );
}
