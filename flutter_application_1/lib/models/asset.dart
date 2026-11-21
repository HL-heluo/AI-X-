import '../core/json_utils.dart';

/// 资产的类型
///
/// 对应 §11.2 的 `assets.kind`。
///
/// 【为什么缩略图要单独当成一种资产，而不是视频的一个附属字段】
/// 因为它们是**三个独立的文件**，各自有独立的大小、独立的存储地址。
/// 视频列表页一屏要显示 9 个视频，如果每个都直接加载视频文件来当封面，
/// 流量和内存都会炸。缩略图是单独上传的一张小图，列表读它，点开才读视频。
enum AssetKind {
  image('image', '图片'),
  video('video', '视频'),
  thumbnail('thumbnail', '封面');

  const AssetKind(this.wire, this.label);

  final String wire;
  final String label;

  static AssetKind fromWire(String wire) {
    for (final k in AssetKind.values) {
      if (k.wire == wire) return k;
    }
    throw FormatException(
      '未知的资产类型 "$wire"。定义在 lib/models/asset.dart。',
    );
  }
}

/// 一份产物资产
///
/// 对应 §11.2 的 `assets` 表。作品页的网格、结果页的展示、视频播放都读它。
///
/// ─────────────────────────────────────────────────────────
/// 【⚠️ 关于 publicUrl 这个名字里的 "public"】
///
/// 这个名字是**故意起得这么啰嗦**的。
///
/// 上游（即梦）返回的产物 URL 带签名且**只活 1 小时**。后端的工作是在那 1 小时内
/// 把文件转存到我们自己的对象存储，然后给我们一个永久地址 —— 那才是这个字段。
///
/// 如果哪天有人想「先用 provider 的 URL 顶一下，反正能显示」，
/// 他必须把这个字段名改短才顺手。改名字这个动作会卡他一下，
/// 让他有机会看到这段注释。**用名字设一道坎，比写在文档里没人看强。**
/// ─────────────────────────────────────────────────────────
class Asset {
  const Asset({
    required this.id,
    required this.kind,
    required this.publicUrl,
    this.taskId,
    this.mime,
    this.sizeBytes,
    this.durationSec,
    this.width,
    this.height,
    this.isAiGenerated = true,
    this.createdAt,
  });

  final String id;
  final AssetKind kind;

  /// **永久**可访问的地址（我们自己的对象存储）。见类注释。
  final String publicUrl;

  /// 由哪个任务生成。用户上传的参考图没有它。
  final String? taskId;

  /// MIME 类型，如 `image/png` / `video/mp4`。播放器挑解码方式要用。
  final String? mime;

  final int? sizeBytes;

  /// 视频时长（秒）。图片为 null。
  final int? durationSec;

  final int? width;
  final int? height;

  /// 是否为 AI 生成内容。
  ///
  /// §§10.1 要求 AI 生成内容必须带**可见标识**（《人工智能生成合成内容标识办法》，
  /// 2025-09-01 起施行，是法律义务不是可选项）。
  /// §11.2 规定这一列**恒为 true** —— 我们平台上所有产物都是 AI 生成的。
  ///
  /// 【那为什么还要保留这个字段、不当成常量 true 处理】
  /// 因为将来可能有「用户上传的原图」混进资产列表（比如参考图），
  /// 那些**不该**打「AI 生成」标。留一个字段，那天到了不用改数据结构。
  /// 默认值给 true 是安全的：漏了字段时宁可多打标，不能少打。
  final bool isAiGenerated;

  final DateTime? createdAt;

  /// 宽高比。用于作品网格里按真实比例排版（不裁切成正方形）。
  ///
  /// 【为什么值得有个 getter】网格要按比例算每格高度。
  /// 宽高缺失时返回 null，让调用方决定退化成什么默认值 ——
  /// 这里**不能随便返回 1.0 假装是方的**，那会让竖屏视频被排版成正方形。
  double? get aspectRatio {
    final w = width;
    final h = height;
    if (w == null || h == null || w <= 0 || h <= 0) return null;
    return w / h;
  }

  /// 是否是视频（决定网格上要不要盖播放按钮）。
  bool get isVideo => kind == AssetKind.video;

  factory Asset.fromJson(Map<String, dynamic> json) => Asset(
        id: json.requireInt(json['id'], field: 'id').toString(),
        kind: AssetKind.fromWire(json.stringOr(json['kind'], 'image')),
        publicUrl: json.stringOr(json['public_url']),
        taskId: json.asStringOrNull(json['task_id']),
        mime: json.asStringOrNull(json['mime']),
        sizeBytes: json.asIntOrNull(json['size_bytes'], field: 'size_bytes'),
        durationSec:
            json.asIntOrNull(json['duration_sec'], field: 'duration_sec'),
        width: json.asIntOrNull(json['width'], field: 'width'),
        height: json.asIntOrNull(json['height'], field: 'height'),
        // 默认 true：漏了字段时宁可多打 AI 标识，不能少打（合规底线）
        isAiGenerated: json.boolOr(json['is_ai_generated'], true),
        createdAt: json.asDateTimeOrNull(json['created_at']),
      );
}
