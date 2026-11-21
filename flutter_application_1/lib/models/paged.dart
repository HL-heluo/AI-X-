import '../core/json_utils.dart';

/// 分页结果
///
/// 流水页和作品页都是「越滚越多」的列表，接口按页返回。
///
/// 【为什么要写成泛型 `Paged<T>` 而不是给流水和作品各写一个】
/// 因为翻页这件事（记页码、判断有没有下一页、把新一页追加到已有列表后面）
/// 和具体的元素类型**完全无关**。写两遍就是两份要同步维护的翻页 bug。
/// 泛型化之后，`AsyncNotifier` 里那段「append + 更新页码」的逻辑也能只写一份。
///
/// 【前端类比】≈ 后端返回的 `{ list: [...], total: 100, page: 1, page_size: 20 }`。
class Paged<T> {
  const Paged({
    required this.items,
    this.page = 1,
    this.pageSize = 20,
    this.total = 0,
  });

  /// 本页数据。
  final List<T> items;

  /// 当前页码，**从 1 开始**（不是下标）。
  ///
  /// 【为什么要特意标注】这是最容易错一位的地方：把 1 当第 0 页传给后端，
  /// 用户会看到「第一页是空的，第二页才有东西」。
  final int page;

  final int pageSize;

  /// 总条数。
  final int total;

  /// 还有没有下一页。
  ///
  /// 【注意这个判断的边界是「已加载数 < 总数」，不是「本页满了」】
  /// 「本页返回了 20 条 = 满页」不代表还有下一页 —— 正好 20 条时两种可能都有。
  /// 只有拿 `page * pageSize < total` 才是可靠的。
  bool get hasMore => page * pageSize < total;

  /// 空页，用于「还没拉到数据」。
  static Paged<T> empty<T>() => Paged<T>(items: const []);

  /// 从 JSON 构造。
  ///
  /// [fromItem] 由调用方传进来，负责把单个元素转成 [T]。
  /// 【为什么不让 Paged 自己知道怎么解析元素】因为它不该知道 —— 一旦知道，
  /// 它就和具体模型耦合了，泛型也就白写了。
  factory Paged.fromJson(
    Map<String, dynamic> json,
    T Function(Map<String, dynamic>) fromItem,
  ) {
    // 【关于 items 的两种写法】§12.1 没规定列表字段叫什么。
    // `items` 是更常见的写法，`list` 也有可能，两种都收下，免得接后端那天才发现。
    final rawItems = json['items'] ?? json['list'];
    return Paged<T>(
      items: json
          .asJsonList(rawItems, field: 'items')
          .map(fromItem)
          .toList(growable: false),
      page: json.intOr(json['page'], 1, field: 'page'),
      pageSize: json.intOr(json['page_size'], 20, field: 'page_size'),
      total: json.intOr(json['total'], 0, field: 'total'),
    );
  }

  @override
  String toString() => 'Paged<$T>(page: $page, items: ${items.length}, total: $total)';
}
