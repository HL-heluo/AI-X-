import '../constants/error_codes.dart';

/// 全 App 唯一的异常类型
///
/// 【为什么只留一个异常类型，而不是每种错误一个类】
/// 因为调用方（UI）真正关心的只有一件事：**「这次失败我该怎么办」**。
/// 而「怎么办」已经由 [ApiErrorCode] 回答了。
/// 如果分成 `InsufficientCreditsException` / `RateLimitedException` / ...
/// 七八个子类，UI 那边就得写一串 `on XxxException catch`；
/// 有了错误码枚举，一个 `switch (e.code)` 就够，而且**新增错误码时是编译错误**
/// （switch 会提示你没穷尽），不会像 `on XxxException` 那样悄悄漏掉。
///
/// 【另外为什么不用 `throw '字符串'`】
/// 字符串异常丢掉了所有结构信息 —— 拿到它你既不知道是哪个错误码，
/// 也不知道 HTTP 状态码是多少，只能靠 `contains('积分')` 这种脆弱写法猜。
class AppException implements Exception {
  const AppException({
    required this.message,
    this.code,
    this.httpStatus,
    this.body,
  });

  /// 面向**开发**的描述，用于日志和排查。不要直接显示给用户 ——
  /// 给用户看的走 [userMessage]。
  final String message;

  /// 后端返回的业务错误码。**为 null 表示这不是后端给的业务错误**
  /// （比如断网、超时、JSON 解析失败），这时只能给一句通用提示。
  final ApiErrorCode? code;

  /// HTTP 状态码。断网时为 null。
  final int? httpStatus;

  /// 错误响应里捎带的负载。
  ///
  /// 【为什么错误里还要带数据】因为 §12.3 有一条特殊的：
  /// `DUPLICATE_REQUEST` 的客户端行为是**静默复用已存在的任务** ——
  /// 也就是说这个「错误」其实要把任务本体带回来，客户端才能直接用它。
  /// 没有这个字段的话，客户端拿到 409 只知道「重复了」，却不知道复用哪一个。
  ///
  /// 只有 `DUPLICATE_REQUEST` 用得上它，其余错误都是 null。
  final Map<String, dynamic>? body;

  /// 从一次 HTTP 响应构造。
  ///
  /// [codeWire] 是响应体里的错误码字符串（如 `'INSUFFICIENT_CREDITS'`）。
  /// 认不出来时 [code] 为 null —— **降级成通用错误，而不是崩掉**。
  /// 理由：后端加新错误码时，老版本 App 还在用户手机上跑，
  /// 那种情况下「未知错误，请稍后重试」远好过一个红色白屏。
  factory AppException.fromResponse({
    required int httpStatus,
    String? codeWire,
    String? message,
    Map<String, dynamic>? body,
  }) {
    final code = ApiErrorCode.tryFromWire(codeWire);
    return AppException(
      code: code,
      httpStatus: httpStatus,
      body: body,
      message: message ?? code?.defaultMessage ?? 'HTTP $httpStatus 请求失败',
    );
  }

  /// 网络层失败：断网、DNS 失败、超时、连不上。
  ///
  /// 【为什么要单独一个构造】因为这类的处理方式和业务错误完全不同 ——
  /// 业务错误要说清「哪里不对」，网络错误只需说「检查下网络」，且**可以无脑重试**。
  factory AppException.network([String? detail]) => AppException(
        message: detail == null ? '网络请求失败' : '网络请求失败：$detail',
      );

  /// 响应能拿到、但解析不出来（字段缺失、类型不对、不是合法 JSON）。
  ///
  /// 【为什么这个要单独拎出来】它和网络错误长得像但性质相反：
  /// 网络错误是**环境问题**（重试可能好），
  /// 解析失败是**契约问题**（重试一万次都一样）。混在一起会浪费排查时间。
  factory AppException.parse(String detail) =>
      AppException(message: '响应解析失败：$detail');

  /// 未登录 / 登录已过期（HTTP 401）。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【⚠️ 这是 §12.3 的一个缺口，需要补进契约】
  ///
  /// §12.3 的错误码表里**没有定义 401**，但 App 必然会遇到它 ——
  /// JWT 会过期，用户可能在别处登出了。没有约定的话，
  /// 每个 repository 都得自己判断「这个 401 该不该触发登出」，迟早不一致。
  ///
  /// 本项目的处理：401 统一走这个构造，[code] 保持 null（它不是业务错误码），
  /// 由调用方用 [isUnauthorized] 判断并触发登出。**接真后端前建议让后端
  /// 也定义成一个 `UNAUTHORIZED` 错误码，那时这里就能改成走 code 判断。**
  /// ─────────────────────────────────────────────────────────
  factory AppException.unauthorized([String? detail]) => AppException(
        httpStatus: unauthorizedStatus,
        message: detail ?? '未登录或登录已过期',
      );

  /// HTTP 401 的约定值。
  static const int unauthorizedStatus = 401;

  /// 给用户看的一句话。
  ///
  /// 优先用错误码自带的兜底文案；没有错误码（断网/解析失败/401）时给通用话术。
  /// 【注意】后端返回的 [message] **不在这里显示** —— 它是给开发看的。
  String get userMessage {
    if (code != null) return code!.defaultMessage;
    if (isUnauthorized) return '登录已过期，请重新登录';
    return '出错了，请稍后重试';
  }

  /// 是否是「未登录 / 登录已过期」。
  ///
  /// 【为什么这个判断要收在这里】因为触发登出是个**有副作用**的动作，
  /// 绝不能散落在各个 repository 里各写一遍 —— 那样只要有一处忘了，
  /// 就会出现「token 早就失效了，页面还在一直重试、一直转圈」。
  bool get isUnauthorized => httpStatus == unauthorizedStatus;

  /// 是否是「幂等键重复」。
  ///
  /// 【为什么值得给个 getter】因为这一条的处理方式**和所有其它错误都相反**：
  /// 其它错误要弹提示，它要**当成成功**（说明这次提交后端已经收到过了，
  /// 复用那次的任务就行）。UI 里写 `if (e.isDuplicateRequest)` 比
  /// `if (e.code == ApiErrorCode.duplicateRequest)` 更能表达意图。
  /// 顺带也避免了每个调用方都去 import error_codes.dart。
  bool get isDuplicateRequest => code == ApiErrorCode.duplicateRequest;

  /// 是否可以原样重试。
  ///
  /// provider 失败（积分已退回）、队列已满、网络抖动 —— 这三种重试有意义。
  /// 「积分不足」「内容未通过审核」重试一百次也是同样结果，不算可重试。
  bool get isRetryable => switch (code) {
        ApiErrorCode.providerError ||
        ApiErrorCode.queueSaturated ||
        ApiErrorCode.rateLimited =>
          true,
        // code 为 null 时是网络/解析问题；网络问题可重试
        null => httpStatus == null,
        ApiErrorCode.insufficientCredits ||
        ApiErrorCode.invalidPrompt ||
        ApiErrorCode.imageTooLarge ||
        ApiErrorCode.duplicateRequest ||
        ApiErrorCode.contentRejected ||
        // 邀请码错是**输入**问题，原样重试一万次还是同一个码
        ApiErrorCode.inviteInvalid =>
          false,
      };

  @override
  String toString() {
    final parts = <String>[
      if (httpStatus != null) 'HTTP $httpStatus',
      if (code != null) code!.wire,
      message,
    ];
    return 'AppException(${parts.join(' · ')})';
  }
}
