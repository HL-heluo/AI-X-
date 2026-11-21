import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_exception.dart';
import '../../data/remote/work_marketplace_repository.dart';
import '../../router/app_router.dart';

class PublicationPage extends ConsumerStatefulWidget {
  const PublicationPage({
    super.key,
    required this.assetId,
    required this.evidenceId,
  });

  final String assetId, evidenceId;

  @override
  ConsumerState<PublicationPage> createState() => _PublicationPageState();
}

class _PublicationPageState extends ConsumerState<PublicationPage> {
  final _title = TextEditingController();
  final _author = TextEditingController();
  final _description = TextEditingController();
  final _form = GlobalKey<FormState>();
  bool _visible = false;
  bool _showPrompt = false;
  bool _loaded = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _title.dispose();
    _author.dispose();
    _description.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final publication = await ref
          .read(workMarketplaceProvider)
          .publication(widget.assetId);
      if (!mounted) return;
      _title.text = publication.title;
      _author.text = publication.authorName;
      _description.text = publication.description;
      setState(() {
        _loaded = true;
        _visible = publication.visible;
        _showPrompt = publication.showPrompt;
        _error = null;
      });
    } on AppException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    }
  }

  Future<void> _save({bool revoke = false}) async {
    if (_busy || (!revoke && !_form.currentState!.validate())) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final repository = ref.read(workMarketplaceProvider);
      if (revoke) {
        await repository.revoke(widget.assetId);
      } else {
        await repository.publish(
          widget.assetId,
          WorkPublication(
            visible: true,
            title: _title.text.trim(),
            authorName: _author.text.trim(),
            description: _description.text.trim(),
            showPrompt: _showPrompt,
          ),
        );
      }
      if (!mounted) return;
      setState(() {
        _visible = !revoke;
        if (revoke) _showPrompt = false;
      });
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(revoke ? '已撤销公开' : '公开信息已保存')));
    } on AppException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copy() async {
    final path = AppRoutes.verification(widget.evidenceId);
    final value = kIsWeb
        ? Uri.base.replace(fragment: path).toString()
        : widget.evidenceId;
    await Clipboard.setData(ClipboardData(text: value));
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(kIsWeb ? '已复制核验链接' : '已复制存证编号')));
    }
  }

  String? _required(String? value) =>
      value == null || value.trim().isEmpty ? '请填写此项' : null;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('公开存证')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: Form(
            key: _form,
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                if (_loaded) ...[
                  Text(_visible ? '访客可凭编号查询' : '当前仅自己可见'),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _title,
                    validator: _required,
                    maxLength: 120,
                    decoration: const InputDecoration(labelText: '公开标题'),
                  ),
                  TextFormField(
                    controller: _author,
                    validator: _required,
                    maxLength: 80,
                    decoration: const InputDecoration(labelText: '作者显示名'),
                  ),
                  TextFormField(
                    controller: _description,
                    maxLength: 2000,
                    maxLines: 3,
                    decoration: const InputDecoration(labelText: '作品介绍'),
                  ),
                  SwitchListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                    title: const Text('公开原提示词'),
                    value: _showPrompt,
                    onChanged: _busy
                        ? null
                        : (value) => setState(() => _showPrompt = value),
                  ),
                  const SizedBox(height: 10),
                  FilledButton(
                    onPressed: _busy ? null : () => _save(),
                    child: Text(_visible ? '保存公开资料' : '公开存证'),
                  ),
                  if (_visible)
                    Wrap(
                      alignment: WrapAlignment.center,
                      spacing: 8,
                      children: [
                        TextButton(
                          onPressed: _busy ? null : _copy,
                          child: Text(kIsWeb ? '复制核验链接' : '复制存证编号'),
                        ),
                        TextButton(
                          onPressed: () => Navigator.of(context)
                              .pushNamed<void>(
                                AppRoutes.verification(widget.evidenceId),
                              ),
                          child: const Text('查看公开页'),
                        ),
                        TextButton(
                          onPressed: _busy ? null : () => _save(revoke: true),
                          child: const Text('撤销公开'),
                        ),
                      ],
                    ),
                ],
                if (!_loaded && _error == null)
                  const Center(child: CircularProgressIndicator()),
                if (_error case final message?) ...[
                  Text(
                    message,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                  if (!_loaded)
                    TextButton(onPressed: _load, child: const Text('重试')),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
