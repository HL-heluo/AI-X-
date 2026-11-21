import '../models/task.dart';
import '../models/task_cost_estimate.dart';

/// 生成：问价与提交（§12.1 / §7.2）
abstract interface class GenerationRepository {
  /// 问价，返回预估区间与冻结额。
  ///
  /// 【为什么必须「先问价再显示」】
  /// §13.4 禁止在生成按钮下方写确定数字，而正确的区间又**只有服务端算得出来**
  /// （定价表在后端）。所以在拿到这个结果之前，界面只能显示「计算中…」——
  /// 这个「还没有 → 有了」的两态，是 `CreditFormat.generationHint` 直接支持的。
  ///
  /// [durationSec] 只对视频有意义；图片传 null。
  Future<TaskCostEstimate> estimateCost({
    required TaskKind kind,
    int? durationSec,
    String? ratio,
  });

  /// 提交文生图。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【[idempotencyKey] 为什么是 required 而不是内部自动生成】
  ///
  /// 这是整个接口设计里最容易做错的一个地方。
  ///
  /// 幂等键的作用是「**同一次提交意图**，不管重发多少次，服务端只认一次」。
  /// 所以它必须在**用户按下生成按钮的那一刻**生成一次，
  /// 然后在后续所有重试里**复用同一个值**。
  ///
  /// 如果让这个方法内部 `Uuid().v4()` 自动生成，那么：
  /// * 用户双击生成按钮 → 两个请求 → 两个不同的键 → **建两个任务，扣两次钱**；
  /// * 网络超时后自动重试 → 又一次扣钱。
  /// 也就是说，自动生成会让这道闸门**完全失效**，而且失效得很隐蔽
  /// （代码看起来还挺优雅）。
  ///
  /// 设成 required，调用方就必须显式地回答一个问题：
  /// 「这次重试，还是不是原来那个意图？」——这本来就该由它回答。
  ///
  /// 调用方（生成页的 Notifier）的写法：
  /// ```dart
  /// final key = _pendingKey ??= const Uuid().v4();  // 每次「开始生成」生成一次
  /// await repo.submitImage(prompt: p, idempotencyKey: key);
  /// // 成功后 _pendingKey = null，下次点生成才是新意图
  /// ```
  /// ─────────────────────────────────────────────────────────
  Future<Task> submitImage({
    required String prompt,
    required String idempotencyKey,
    String? aspectRatio,
  });

  /// 提交图生视频（v1 的主链路：拿一张生成的图去生成视频）。
  ///
  /// [sourceAssetId] 是已经上传好的参考图，**必填** ——
  /// §5 要求「参考图必须公网可访问」，所以它必须先落在我们自己的对象存储上，
  /// 不能直接把用户手机里的图丢给 provider。
  Future<Task> submitVideo({
    required String prompt,
    required String sourceAssetId,
    required String idempotencyKey,
    int durationSec = 5,
    String? ratio,
  });

  // 【这里为什么没有文生视频（text_to_video）】
  // 因为它是 v2 的能力（§14.2），v1 的创作页只有「图片」和「视频」两个模式，
  // 而 v1 的「视频」走的是图生视频 —— 图片是入口，视频是卖点，
  // 中间那一步「选一张生成的图」是刻意保留的（§14.4 讲了为什么图片必须排在视频前面）。
}
