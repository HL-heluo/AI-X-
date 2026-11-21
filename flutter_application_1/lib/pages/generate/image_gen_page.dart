import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../core/constants/error_codes.dart';
import '../../core/network/api_exception.dart';
import '../../models/task.dart';
import '../../providers/generation_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import 'widgets/gen_parts.dart';

/// 图片生成页（§13.2 的 `imageGen`）
///
/// ─────────────────────────────────────────────────────────
/// 【这一页为什么不是从首页那张卡「就地生成」】
///
/// 首页那张卡是**入口**，它要在最小的屏幕空间里同时容纳
/// 「图片 / 视频」两个模式的切换。真正下单需要的那些东西 ——
/// 画面比例、报价区间、提交失败的说明 —— 塞进去会把首屏撑爆。
///
/// 拆成独立一页还有个额外的好处：它有**返回**。用户在报价出来之前
/// 改主意了，可以退出去，什么也没发生。首页那张卡里没有这个退路。
/// ─────────────────────────────────────────────────────────
///
/// 【幂等键的完整生命周期（这段是全项目最重要的一处）】
///
/// 见 `GenerationRepository.submitImage` 上那段长注释。这里落地成：
///
///   · **第一次按下生成** → 生成一个 UUID，存进 [_intentKey]；
///   · **提交失败后再点一次** → **复用**同一个 UUID
///     （如果第一次其实已经到服务端了，只是响应丢了，复用才能让后端认出
///      「这是同一次意图」并返回那个任务，而不是又建一个、又扣一次钱）；
///   · **用户改了提示词或参数** → [_intentKey] 清空。
///     改了内容就是**新的意图**，必须换新的键 ——
///     否则用户改成另一句话再提交，会被后端当成重复而拿回旧任务，
///     他会觉得「我明明改了，生成的还是上一张」。
///
/// 所以清空动作挂在两个地方：输入框的 listener，和每个参数选项的 onChanged。
/// **漏掉任何一个都会造出上面那第二种 bug**，而且很难复现。
/// ─────────────────────────────────────────────────────────
class ImageGenPage extends ConsumerStatefulWidget {
  const ImageGenPage({super.key, this.initialPrompt});

  /// 从首页带过来的提示词（用户在入口卡里已经打了一半的）。
  final String? initialPrompt;

  @override
  ConsumerState<ImageGenPage> createState() => _ImageGenPageState();
}

class _ImageGenPageState extends ConsumerState<ImageGenPage> {
  late final TextEditingController _prompt;

  /// 画面比例。默认 1:1 —— 图片最通用的比例，也是最不容易出错的那个。
  String _ratio = _ratios.first.value;

  bool _submitting = false;

  /// 最近一次提交失败的原因。**只活在这一页里** ——
  /// 它是一次表单动作的结果，不是任务状态（§8.4 禁止的是后者）。
  AppException? _error;

  /// 本次「提交意图」的幂等键。见类注释。
  String? _intentKey;

  static const List<GenChoice<String>> _ratios = [
    GenChoice('1:1', '1:1'),
    GenChoice('3:4', '3:4'),
    GenChoice('4:3', '4:3'),
    GenChoice('16:9', '16:9'),
    GenChoice('9:16', '9:16'),
  ];

  @override
  void initState() {
    super.initState();
    _prompt = TextEditingController(text: widget.initialPrompt ?? '');
    // 改一个字就是一次新意图（见类注释）
    _prompt.addListener(_forgetIntent);
  }

  @override
  void dispose() {
    _prompt.removeListener(_forgetIntent);
    _prompt.dispose();
    super.dispose();
  }

  void _forgetIntent() {
    _intentKey = null;
  }

  CostQuery get _costQuery => (
        kind: TaskKind.textToImage,
        durationSec: null,
        ratio: _ratio,
      );

  /// 提交前的就地校验。
  ///
  /// 【为什么前端也要拦一次】后端当然会拦（Mock 里也有），但让用户
  /// 为一句空的提示词跑一趟网络、再等一个红字回来，是没必要的往返。
  /// 而且离线时后端根本拦不到 —— 那时前端这一道就是唯一的。
  ///
  /// 【文案为什么从错误码取】见 `localFormError` 的注释。
  AppException? _validate(String prompt) {
    if (prompt.isEmpty) return localFormError(ApiErrorCode.invalidPrompt);
    if (prompt.length > GenPromptField.maxLength) {
      return localFormError(ApiErrorCode.invalidPrompt);
    }
    return null;
  }

  Future<void> _submit() async {
    final prompt = _prompt.text.trim();

    final invalid = _validate(prompt);
    if (invalid != null) {
      setState(() => _error = invalid);
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      final task = await ref.read(generationSubmitterProvider).submitImage(
            prompt: prompt,
            idempotencyKey: _intentKey ??= const Uuid().v4(),
            aspectRatio: _ratio,
          );

      if (!mounted) return;
      // 这次意图已经落地，下一次点生成才是新意图
      _intentKey = null;

      // 【为什么是 pushReplacement 而不是 push】
      // 结果页要顶掉这一页：用户已经提交了，再回到这个填好了的、按钮还亮着的
      // 表单页，下一步动作只能是「再点一次生成」—— 那是最容易造成重复消费的
      // 一种界面状态。让他返回时直接回到首页。
      //
      // 【成功后为什么不 setState】这一页马上就要被换掉了。
      // 在成功的路径上写 setState 会踩到「widget 已 dispose」——
      // 而这类异常在真机上只表现为一行日志，很难归因。
      await Navigator.of(context).pushReplacement<void, void>(
        AppRoutes.imageResultRoute<void>(task.id),
      );
    } on AppException catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _error = e;
      });
      await _handleSubmitError(e);
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _error = AppException(message: '提交时出现未预期的错误：$e');
      });
    }
  }

  /// 有些错误光说一句没用，得给用户一条出路。
  Future<void> _handleSubmitError(AppException e) async {
    // 积分不足 → 他是想知道钱去哪了，而不是想知道「不足」
    if (e.code != ApiErrorCode.insufficientCredits) return;

    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: AppColors.bgWarm,
        title: const Text(
          '可用积分不足',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
        content: const Text(
          // 【为什么要点出「冻结中」】用户看得见余额，看不见冻结。
          // 有任务在跑时余额也被扣着，不说清楚他会以为钱被吞了。
          '可用积分 = 总余额 − 冻结中。有任务正在生成时，那部分积分也被占着。\n\n'
          '去积分页可以看到余额和每一笔流水。',
          style: TextStyle(fontSize: 13.5, height: 1.6),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('知道了', style: TextStyle(color: AppColors.taupe)),
          ),
          TextButton(
            key: const Key('gen.errorAction'),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('去看积分', style: TextStyle(color: AppColors.sage)),
          ),
        ],
      ),
    );

    if (go != true || !mounted) return;
    await Navigator.of(context).push<void>(AppRoutes.creditsRoute<void>());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: genAppBar('生成图片'),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 6, 20, 32),
        children: [
          GenCard(
            label: '画面描述',
            child: GenPromptField(
              controller: _prompt,
              hintText: '如：一只猫在沙滩上奔跑，逆光，电影感…',
            ),
          ),
          const SizedBox(height: 12),
          GenCard(
            label: '画面比例',
            child: GenChoiceRow<String>(
              options: _ratios,
              value: _ratio,
              keyPrefix: 'gen.ratio',
              onChanged: (v) => setState(() {
                _ratio = v;
                _forgetIntent();
              }),
            ),
          ),
          const SizedBox(height: 12),
          GenCard(
            label: '积分',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // §13.4：这个位置只能出现「区间 + 冻结额 + 退回承诺」，
                // 或者「计算中…」。绝不是一个确定的数字。
                GenCostHint(query: _costQuery),
                const SizedBox(height: 8),
                const GenNotice(
                  text: '生成是秒级的。出来的图片可以直接拿去生成视频。',
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          if (_error != null) ...[
            GenErrorBar(message: _error!.userMessage),
            const SizedBox(height: 12),
          ],
          // 提交按钮的可用性跟着输入框走，所以在这一层重建
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: _prompt,
            builder: (context, value, _) => GenSubmitButton(
              label: '开始生成',
              busy: _submitting,
              enabled: value.text.trim().isNotEmpty,
              onTap: _submit,
            ),
          ),
        ],
      ),
    );
  }
}
