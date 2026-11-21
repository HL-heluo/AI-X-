import '../core/json_utils.dart';

/// 用户
///
/// 对应 §11.2 的 `users` 表，以及 §12.1 的 `GET /me`。
///
/// 【为什么这个类这么小】因为 v1 的用户**确实没什么可存的**。
/// 原型时代这里有创作者等级、经验值、徽章数 —— 那些随「接单抽佣」那门生意一起砍了
/// （等级的唯一用途是解锁更高等级的订单）。现在剩下的身份信息只有用户名，
/// 其他都是「这个人的东西」而不是「这个人是什么」：积分在 [CreditAccount]，
/// 作品在 `Asset`，任务在 `Task`。**别把关联数据塞进用户对象**，
/// 那会让每次拉用户信息都顺手把一大堆用不到的东西拖下来。
class User {
  const User({required this.id, required this.username, this.createdAt});

  final String id;
  final String username;

  /// 注册时间。设置页和「关于」里显示「加入于 X」。
  final DateTime? createdAt;

  factory User.fromJson(Map<String, dynamic> json) => User(
        id: json.requireInt(json['id'], field: 'id').toString(),
        username: json.stringOr(json['username']),
        createdAt: json.asDateTimeOrNull(json['created_at']),
      );

  @override
  String toString() => 'User($id, $username)';
}
