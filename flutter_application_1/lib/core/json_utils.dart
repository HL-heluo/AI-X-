/// JSON 取值小工具 —— 全项目解析 JSON 的**唯一入口**
///
/// 【为什么需要这一层】
/// Dart 把 JSON 解码成 `Map<String, dynamic>`，取值全靠手写类型转换。
/// 直接写 `json['balance'] as int` 有两个真实的坑：
///
/// 1. **字段缺失时报错看不懂**。`null as int` 抛的是
///    `type 'Null' is not a subtype of type 'int'` —— 它不告诉你是哪个字段。
///    一个响应有 15 个字段时，你得逐行注释来找。
///
/// 2. **int 和 double 是两种类型**。JSON 里 `20` 解码成 `int`，
///    `20.0` 解码成 `double`。后端某天因为计算方式变了把 `frozen` 返回成 `20.0`，
///    `as int` 当场就炸 —— 而这种炸法在开发期根本预料不到。
///
/// 这一层把这两件事一起处理：**统一收 num，并且报错一定带上字段名**。
///
/// 【为什么写成扩展方法而不是一堆顶层函数】
/// 因为调用点会变成 `asIntOrNull(json['x'])`（函数在左、数据在右）还是
/// `json.asIntOrNull(json['x'])`（数据在左）—— 后者读起来顺，
/// 而且 IDE 打 `json.` 就能把这一组方法全列出来，不用记名字。
library;

/// `Map<String, dynamic>` 的取值扩展。
///
/// 用的时候：`import '../../core/json_utils.dart';`（**不要加前缀**，
/// 扩展方法必须无前缀导入才在作用域内），然后 `json.requireInt(json['id'], field: 'id')`。
extension JsonMapReader on Map<String, dynamic> {
  /// 把一个 JSON 对象（`{...}`）转成 Map。取不到时抛出带名字的错误。
  ///
  /// [field] 用来在报错里指明是哪个字段，调用时一定要传。
  Map<String, dynamic> asJsonMap(Object? value, {String field = '响应体'}) {
    if (value is Map<String, dynamic>) return value;
    if (value is Map) {
      // 有些解析路径给的是 Map<Object?, Object?>（比如 jsonDecode 的嵌套结果），转一层
      return value.map((k, v) => MapEntry(k.toString(), v));
    }
    throw FormatException('字段「$field」应该是对象，实际拿到 ${value.runtimeType}');
  }

  /// 把一个 JSON 数组（`[...]`）转成 List&lt;Map&gt;。取不到时抛出带名字的错误。
  List<Map<String, dynamic>> asJsonList(Object? value, {String field = '列表'}) {
    if (value is! List) {
      throw FormatException('字段「$field」应该是数组，实际拿到 ${value.runtimeType}');
    }
    return value
        .map((e) => asJsonMap(e, field: '$field[]'))
        .toList(growable: false);
  }

  /// 按整数读，读不到返回 null。
  ///
  /// 【为什么用 num 收】见文件头第 2 条：`20` 和 `20.0` 是两种类型。
  /// 这里宽进严出 —— 收 num，但**只接受整数值**。
  /// `20.5` 会抛异常而不是被悄悄截成 20：积分和秒数都不该出现小数，
  /// 出现了说明契约理解错了，必须在开发期就喊出来。
  int? asIntOrNull(Object? value, {String field = ''}) {
    if (value == null) return null;
    if (value is int) return value;
    if (value is num) {
      final asDouble = value.toDouble();
      if (asDouble == asDouble.roundToDouble()) return asDouble.toInt();
      throw FormatException('字段「$field」应该是整数，实际是 $value');
    }
    throw FormatException('字段「$field」应该是整数，实际拿到 ${value.runtimeType}');
  }

  /// 按整数读，读不到就用 [fallback]。
  ///
  /// 【什么时候该用它】用于「缺了也不影响正确性」的可选字段（比如默认比例）。
  /// **积分金额、时长这类影响算钱的字段一律不要用它** —— 那种该用 [requireInt]
  /// 直接炸掉，宁可白屏也不能按错误的金额记账。
  int intOr(Object? value, int fallback, {String field = ''}) =>
      asIntOrNull(value, field: field) ?? fallback;

  /// 按整数读，读不到就抛异常。用于**缺了就没法正确显示**的字段，
  /// 尤其是任何和积分数额相关的字段。
  int requireInt(Object? value, {required String field}) {
    final result = asIntOrNull(value, field: field);
    if (result == null) {
      throw FormatException('缺少必填字段「$field」（应为整数）');
    }
    return result;
  }

  /// 按浮点读，读不到返回 null。
  double? asDoubleOrNull(Object? value, {String field = ''}) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    throw FormatException('字段「$field」应该是数字，实际拿到 ${value.runtimeType}');
  }

  /// 按字符串读，读不到返回 null。
  String? asStringOrNull(Object? value) {
    if (value == null) return null;
    if (value is String) return value;
    // 后端有时把数字型 id 用字符串给，有时又给成数字，两种都收下
    if (value is num) return value.toString();
    throw FormatException('字段应该是字符串，实际拿到 ${value.runtimeType}');
  }

  /// 按字符串读，读不到就用 [fallback]。
  String stringOr(Object? value, [String fallback = '']) =>
      asStringOrNull(value) ?? fallback;

  /// 按布尔读，读不到就用 [fallback]。
  ///
  /// 【这里为什么不用 `value == true` 这种偷懒写法】
  /// 因为 `'true'`（字符串）或 `1`（数字）都不等于 `true`，
  /// 会静默变成 false —— 而 `is_ai_generated` 恰恰是条法律义务字段（§11.2 恒为 true），
  /// 静默为 false 意味着合规标识不显示了。所以类型不对时直接抛。
  bool boolOr(Object? value, bool fallback) {
    if (value == null) return fallback;
    if (value is bool) return value;
    throw FormatException('字段应该是布尔值，实际拿到 ${value.runtimeType}');
  }

  /// 按时间读（ISO 8601 字符串），读不到返回 null。
  ///
  /// 【为什么统一转成 UTC】
  /// 后端返回的时间带时区（`2026-10-12T08:30:00Z` 或 `2026-10-12T16:30:00+08:00`），
  /// 如果各处自己转、各自按本地时区显示，就会出现「同一条流水在两个页面差 8 小时」。
  /// 这里统一落到 UTC 存着，**要显示时再由 UI 层单独转成本地时间** —— 一件事只做一次。
  DateTime? asDateTimeOrNull(Object? value) {
    if (value == null) return null;
    if (value is DateTime) return value.toUtc();
    if (value is String) {
      final parsed = DateTime.tryParse(value);
      if (parsed == null) {
        throw FormatException('时间格式无法解析："$value"（应为 ISO 8601）');
      }
      return parsed.toUtc();
    }
    throw FormatException('时间字段应该是字符串，实际拿到 ${value.runtimeType}');
  }
}
