import 'dart:convert';

import '../core/constants/task_status.dart';
// 无前缀导入：扩展方法必须无前缀才在作用域内（加 `as json` 会让它失效）
import '../core/json_utils.dart';

/// 任务类型
///
/// 对应《工程文档.md》§11.3。v1 上线只有**前两个**：
/// 图片是入口，图生视频是卖点。`textToVideo`（文生视频）属于 v2，
/// 但**枚举里现在就留着**——见下面注释。
///
/// 【为什么把 v2 的类型提前塞进枚举】
/// 因为「类型」是要写进数据库、要跨版本兼容的东西。
/// 如果 v1 只定义两个，等 v2 加第三个时，老版本 App 拿到
/// `text_to_video` 的任务会解析失败（枚举认不出来）。
/// 提前占位，老版本至少能显示成「未知类型」而不是崩掉。
///
/// 【注意这里和「功能」是两回事】枚举里有 ≠ 界面上能选。
/// v1 的创作页只放图片/视频两个模式（视频走图生视频），
/// 文生视频的入口由后端能力开关控制，不由这个枚举控制。
enum TaskKind {
  /// 文生图
  textToImage('text_to_image', '图片'),

  /// 图生视频（要传参考图）
  imageToVideo('image_to_video', '视频'),

  /// 文生视频（v2）
  textToVideo('text_to_video', '视频');

  const TaskKind(this.wire, this.label);

  /// 与后端约定的字符串。
  final String wire;

  /// 给用户看的短标签。
  final String label;

  static TaskKind fromWire(String wire) {
    for (final k in TaskKind.values) {
      if (k.wire == wire) return k;
    }
    throw FormatException(
      '未知的任务类型 "$wire"。定义在 lib/models/task.dart。',
    );
  }

  /// 这个类型是否需要一张参考图。
  ///
  /// 【为什么值得写成 getter】提交前校验要用它：
  /// 选了「视频」却忘了选图，应该在**按下生成按钮时就拦住**，
  /// 而不是等后端报 `INVALID_PROMPT` 回来再让用户猜哪里错了。
  /// 把判断收在这里，创作页、视频生成页、结果页三处共用一份规则。
  bool get needsSourceImage => this == TaskKind.imageToVideo;
}

/// 任务的生成参数
///
/// 对应 §11.2 的 `params_json` 列。后端存的是一个 JSON 字段，
/// 我们这边给它配类型，免得 UI 到处写 `params['ratio'] as String?`。
///
/// 【为什么这些字段全是可空的】
/// 因为「哪些参数有意义」取决于任务类型：
/// 文生图没有时长，视频才有；比例只有视频需要。用一个全可空的类装它们，
/// 比给图片/视频各建一个参数类要省事，也不会在类型上撒谎。
class TaskParams {
  const TaskParams({
    this.ratio,
    this.duration,
    this.width,
    this.height,
  });

  /// 画面比例，如 `16:9` / `9:16` / `1:1`。
  final String? ratio;

  /// 期望时长（秒）。**这是下单时用户选的值，不是最终成片时长** ——
  /// 最终时长看 `Task.outputDurationSec`，视频的实际长度由 provider 侧的
  /// Agent 自主决定，所以我们才不能在按钮下写死「消耗 X 积分」。
  final int? duration;

  final int? width;
  final int? height;

  /// 空参数（文生图没有额外参数时用它当默认值）。
  static const TaskParams empty = TaskParams();

  factory TaskParams.fromJson(Map<String, dynamic> json) => TaskParams(
        ratio: json.asStringOrNull(json['ratio']),
        duration: json.asIntOrNull(json['duration'], field: 'params.duration'),
        width: json.asIntOrNull(json['width'], field: 'params.width'),
        height: json.asIntOrNull(json['height'], field: 'params.height'),
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        if (ratio != null) 'ratio': ratio,
        if (duration != null) 'duration': duration,
        if (width != null) 'width': width,
        if (height != null) 'height': height,
      };
}

/// 一次生成任务
///
/// 对应《工程文档.md》§11.2。这是全 App 最核心的模型 ——
/// 首页的进行中条、作品页的网格、任务详情、计费流水，全都围绕它。
///
/// ─────────────────────────────────────────────────────────
/// 【⚠️ 这个类里**故意没有** provider_url 字段】
///
/// §11.2 的 tasks 表里确实有 `provider_url` 一列，但 App **永远不该碰它**。
/// 原因是：即梦给的产物 URL **只活 1 小时**（见《即梦API接入.md》），
/// 而我们的账本、作品列表、分享链接都要求**永久可访问**。
/// 所以后端负责把产物转存到我们自己的 OSS，App 只认 `Asset.publicUrl`。
///
/// 如果哪天你发现需要加这个字段，先停下来想清楚：
/// 你多半是想要「某种构造出来的 URL」，那应该去查 `Asset`，而不是抄近路。
/// 把它从类型上断掉，比写一句「请勿使用」的注释可靠得多。
/// ─────────────────────────────────────────────────────────
class Task {
  const Task({
    required this.id,
    required this.kind,
    required this.status,
    required this.prompt,
    this.params = TaskParams.empty,
    this.sourceAssetId,
    this.idempotencyKey,
    this.freezeAmount = 0,
    this.settledAmount,
    this.inputDurationSec,
    this.outputDurationSec,
    this.errorCode,
    this.errorMsg,
    this.queuePosition,
    this.createdAt,
    this.queuedAt,
    this.submittedAt,
    this.finishedAt,
  });

  final String id;
  final TaskKind kind;
  final TaskStatus status;

  /// 用户输入的提示词。
  final String prompt;

  /// 生成参数。
  final TaskParams params;

  /// 图生视频用的参考图（对应 `Asset.id`）。
  final String? sourceAssetId;

  /// 提交时客户端生成的幂等键。
  ///
  /// 【为什么 App 要留一份】因为后端返回 `DUPLICATE_REQUEST` 时会**复用已有任务**，
  /// 客户端要能认出「返回的这个 task 就是我刚提交的那个」。
  /// 拿到这个值去比对，比靠时间戳猜要可靠。
  final String? idempotencyKey;

  /// 下单时**冻结**的积分数。见 §7 的冻结/结算/退回三段式。
  final int freezeAmount;

  /// 结算后**实扣**的积分数。任务没结束前为 null ——
  /// 这个 null 是有意义的：它表示「还不知道最终扣多少」，
  /// 和 settledAmount = 0（确实没扣）是两回事。别用 0 代替 null。
  final int? settledAmount;

  /// 输入的参考图/视频时长（秒），用于计费。
  final int? inputDurationSec;

  /// **成片实际时长**（秒），用于计费。
  ///
  /// 【为什么和 params.duration 分开放】用户下单时选的是「期望 5 秒」，
  /// provider 侧的 Agent 可能给 5.2 秒。计费按**实际成片**算，
  /// 所以才会有「多余自动退回」这回事。
  final int? outputDurationSec;

  /// provider 的原始错误码（如即梦的 `50411`）。
  ///
  /// 【注意它和 status 的分工】status 告诉我们「失败了」，
  /// 这个字段告诉我们「因为什么失败」。App 一般不直接展示它，
  /// 但它要一路透传到日志里 —— 没有它，线上一个「生成失败」就完全无法归因。
  final String? errorCode;

  /// 失败原因（面向开发）。
  final String? errorMsg;

  /// 排队位次。只在 pending/queued 时有意义。
  ///
  /// 【为什么要显示它】§8.2 的硬要求：排队要说实话。
  /// 「前面还有 3 个」远比一个假进度条有用 —— 进度条在排队阶段是编的。
  /// null 表示「取不到位次」，此时 UI 应当不显示这一行，而不是显示成 0。
  final int? queuePosition;

  final DateTime? createdAt;
  final DateTime? queuedAt;
  final DateTime? submittedAt;
  final DateTime? finishedAt;

  // ── 派生值：只读，不存 ────────────────────────────────────
  //
  // 【为什么这些用 getter 现算，而不是当成字段存下来】
  // 「应退积分」是 冻结 − 实扣 的结果。如果把它存成一个字段，
  // 就出现了两个必须保持同步的真身（存的那个和算出来的那个）。
  // 一旦某次赋值漏了，就会出现「流水显示退回 5 积分，余额却只多了 3 积分」。
  // 现算则永远不可能不一致。这也是 `available = balance − frozen` 的同一个道理。

  /// 任务结束时应当退还给用户的积分（冻结额 − 实扣额）。
  ///
  /// 【什么时候有意义】只在**终态**有意义：任务还在跑的时候
  /// settledAmount 是 null，此时这个值会算成「冻结全额」，
  /// 那只是「万一失败会全退」的假设值，**不能拿去展示**。
  int get refundAmount => freezeAmount - (settledAmount ?? 0);

  /// 实际扣除的积分。未结算时为 0，仅用于展示占位。
  int get chargedAmount => settledAmount ?? 0;

  /// 这个任务是否已经算完账（终态且已结算）。
  bool get isSettled => status.isTerminal && settledAmount != null;

  /// 最近一次状态变化的时刻，用于「按时间倒序」排列。
  ///
  /// 【为什么要做这个兜底链】因为不同状态下不是每个时间戳都有值：
  /// 排队的任务没有 submittedAt，被取消的任务可能没有 finishedAt。
  /// 排序要是取了 null 就会乱序。这里按「越靠后越新」的顺序取第一个有值的。
  DateTime? get lastTransitionAt =>
      finishedAt ?? submittedAt ?? queuedAt ?? createdAt;

  factory Task.fromJson(Map<String, dynamic> json) => Task(
        id: json.requireInt(json['id'], field: 'id').toString(),
        kind: TaskKind.fromWire(json.stringOr(json['kind'], 'text_to_image')),
        status: TaskStatus.fromWire(json.stringOr(json['status'], 'pending')),
        prompt: json.stringOr(json['prompt']),
        params: _parseParams(json),
        sourceAssetId: json.asStringOrNull(json['source_asset_id']),
        idempotencyKey: json.asStringOrNull(json['idempotency_key']),
        freezeAmount: json.intOr(json['freeze_amount'], 0, field: 'freeze_amount'),
        settledAmount:
            json.asIntOrNull(json['settled_amount'], field: 'settled_amount'),
        inputDurationSec: json.asIntOrNull(
          json['input_duration_sec'],
          field: 'input_duration_sec',
        ),
        outputDurationSec: json.asIntOrNull(
          json['output_duration_sec'],
          field: 'output_duration_sec',
        ),
        errorCode: json.asStringOrNull(json['error_code']),
        errorMsg: json.asStringOrNull(json['error_msg']),
        queuePosition:
            json.asIntOrNull(json['queue_position'], field: 'queue_position'),
        createdAt: json.asDateTimeOrNull(json['created_at']),
        queuedAt: json.asDateTimeOrNull(json['queued_at']),
        submittedAt: json.asDateTimeOrNull(json['submitted_at']),
        finishedAt: json.asDateTimeOrNull(json['finished_at']),
      );

  /// 读取生成参数。
  ///
  /// 【为什么这里要兼容两种写法】后端 DB 里存的是 `params_json` 这一列，
  /// 但接口返回时可能给成 `params` 对象（更自然），也可能偷懒直接回传
  /// 那根 JSON 字符串。两种都收下，免得接后端那天才发现要改。
  /// `params` 优先 —— 它才是正常契约。
  static TaskParams _parseParams(Map<String, dynamic> json) {
    final direct = json['params'];
    if (direct is Map) {
      return TaskParams.fromJson(json.asJsonMap(direct, field: 'params'));
    }
    final raw = json['params_json'];
    if (raw is String && raw.isNotEmpty) {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        return TaskParams.fromJson(json.asJsonMap(decoded, field: 'params_json'));
      }
    }
    return TaskParams.empty;
  }
}
