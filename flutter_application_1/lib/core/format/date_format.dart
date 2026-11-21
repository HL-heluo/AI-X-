/// 时间的展示格式 —— **全项目唯一出处**
///
/// 【为什么要它】流水、作品、任务详情都要显示时间。移动端列表里
/// 「2026-10-12 15:03:44」又长又难扫，用户真正想知道的是**新旧**
/// ——「刚刚」「3 小时前」比一串数字有用得多。
///
/// 【为什么不引 intl】见 pubspec 顶部那条纪律：依赖面越窄越好。
/// 我们需要的只有这一种相对格式，intl 会带来一整套 locale 数据
/// 和一份需要跟着 Flutter 升级维护的版本约束，为一个函数不值当。
///
/// 【和 [CreditFormat] 的分工】那个管**钱的措辞**（冻结/结算/退回），
/// 这个只管**时间怎么读**。两者都不许各自实现第二遍。
library;

/// 把时间显示成列表里好扫的一句话。
///
/// * 一分钟内 → `刚刚`
/// * 一小时内 → `12 分钟前`
/// * 同一天   → `3 小时前`
/// * 昨天     → `昨天 18:03`
/// * 今年     → `3月5日`
/// * 更早     → `2025年3月5日`
///
/// [now] 只为测试注入（时间戳算出来的结果没法断言），正常调用不要传。
String formatRelativeTime(DateTime? time, {DateTime? now}) {
  if (time == null) return '';

  final current = now ?? DateTime.now();
  final local = time.toLocal();
  final diff = current.difference(local);

  // 【未来时间要单独兜住】客户端时钟可能比服务端慢几分钟，
  // 于是刚写下的流水会「来自未来」。此时 diff 是负数，
  // 上面所有分支都会算出一个荒唐的结果（「-3 分钟前」），
  // 所以这里直接退回绝对时刻，至少不会显得像 bug。
  if (diff.isNegative) return '${_two(local.hour)}:${_two(local.minute)}';

  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inMinutes < 60) return '${diff.inMinutes} 分钟前';

  // 【为什么用「日历日」比较，而不是 `diff.inHours < 24`】
  // 23:50 到次日 00:10 只差 20 分钟，但那是「昨天」的事；
  // 反过来 00:01 到 23:59 是同一天，差快 24 小时却该说「今天」。
  // 按时间差判断会把这两种都归错，按日期判断才对。
  final today = DateTime(current.year, current.month, current.day);
  final that = DateTime(local.year, local.month, local.day);
  final dayGap = today.difference(that).inDays;

  if (dayGap == 0) return '${diff.inHours} 小时前';
  if (dayGap == 1) return '昨天 ${_two(local.hour)}:${_two(local.minute)}';
  if (local.year == current.year) return '${local.month}月${local.day}日';
  return '${local.year}年${local.month}月${local.day}日';
}

/// 只显示日期（用于「加入于 X」这类不关心时刻的地方）。
String formatDate(DateTime? time) {
  if (time == null) return '';
  final local = time.toLocal();
  return '${local.year}年${local.month}月${local.day}日';
}

/// 补零到两位。
String _two(int value) => value.toString().padLeft(2, '0');
