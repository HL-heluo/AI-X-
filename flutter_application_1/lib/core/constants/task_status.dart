/// 任务状态 —— **全项目唯一定义处**
///
/// 对应《工程文档.md》§11.3。别处引用状态一律用这个枚举，
/// 不许再写字符串字面量，也不许造同义词（这是文档 §0.4「术语锁定」立的规矩：
/// 一处写 `canceled`、另一处写 `cancelled`，最后就对不上了）。
///
/// 【为什么任务状态是后端说了算】
/// 一次生成请求要交给即梦的异步接口，提交后只能轮询等结果，
/// 全过程约 10 分钟，而且产物 URL 只活 1 小时。
/// 这些事情都发生在服务端，App 只是个观察者 ——
/// 所以 App **绝不把任务状态存在自己内存里**，App 重开必须能从服务端拉回全部进行中任务。
///
/// 【前端类比】这就是后端的 status 字段，只是我们给它配了类型和中文。
enum TaskStatus {
  /// 已创建，待入队
  pending('pending', '待提交'),

  /// 排队中，还没提交给 provider
  queued('queued', '排队中'),

  /// 已提交给 provider，正在生成
  submitted('submitted', '生成中'),

  /// 成功，产物已转存
  succeeded('succeeded', '已完成'),

  /// provider 报错 / 超时
  failed('failed', '生成失败'),

  /// 内容审核未通过
  rejected('rejected', '未通过审核'),

  /// 用户取消
  canceled('canceled', '已取消'),

  /// 超过 provider 的 12 小时窗口
  expired('expired', '已过期');

  const TaskStatus(this.wire, this.label);

  /// 与后端约定的字符串。**序列化只能用这个，不能用 enum 的 name。**
  ///
  /// 【为什么单独存一份】Dart 的 `enum.name` 就是标识符本身，看起来够用；
  /// 但把「对外契约」和「代码里的标识符」绑死是危险的 ——
  /// 哪天有人把 `canceled` 重命名成 `cancelled`，序列化会静默跟着变，
  /// 后端却还认 `canceled`。显式写死一个 wire 值，重命名才不会伤到契约。
  final String wire;

  /// 给用户看的中文。
  ///
  /// 【为什么状态文案也放这里】作品页、任务详情、状态标签都要显示它，
  /// 分散在三处写就会漂移（一处「生成中」一处「进行中」）。集中一份。
  final String label;

  /// 从后端字符串还原。
  ///
  /// 【为什么认不出就抛异常，而不是给个默认值】
  /// 认不出来意味着**后端加了新状态而前端不知道** —— 这是契约漂移，
  /// 必须在开发期大声报出来。悄悄退化成某个默认值，会让线上出现
  /// 「状态显示成排队中，其实早就失败了」这种最难查的 bug。
  static TaskStatus fromWire(String wire) {
    for (final s in TaskStatus.values) {
      if (s.wire == wire) return s;
    }
    throw FormatException(
      '未知的任务状态 "$wire"。任务状态的唯一定义在 lib/core/constants/task_status.dart，'
      '后端若新增了状态，这里要同步加上。',
    );
  }

  /// 终态：不会再变了，轮询到它就该停。
  ///
  /// 【为什么这个 getter 重要】轮询的停止条件就靠它。
  /// 漏掉一个终态 = 一个永远转下去的定时器，既费电又费流量。
  bool get isTerminal => switch (this) {
        TaskStatus.succeeded ||
        TaskStatus.failed ||
        TaskStatus.rejected ||
        TaskStatus.canceled ||
        TaskStatus.expired =>
          true,
        TaskStatus.pending ||
        TaskStatus.queued ||
        TaskStatus.submitted =>
          false,
      };

  /// 进行中（非终态）。
  ///
  /// 正好对应接口 `GET /tasks?status=active|done` 里的 `active`：
  /// 首页的「进行中任务条」和作品页的「进行中」分段都按它筛。
  bool get isActive => !isTerminal;
}
