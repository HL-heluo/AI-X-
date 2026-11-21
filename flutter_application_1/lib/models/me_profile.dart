import '../core/json_utils.dart';
import 'credit_account.dart';
import 'user.dart';

/// 「我的」这一屏需要的全部信息
///
/// 对应 §12.1 的 `GET /me`：「用户信息 + 积分总览」。
///
/// 【为什么用户和积分绑在一起返回，而不是拆成两个接口】
/// 因为它们在业务上是一件事：「这是谁、他有多少积分」。
/// 拆两个接口的话，首页右上角的积分胶囊和「我的」页的昵称会各自异步到达，
/// 中间那一小段时间界面是不一致的。一个接口一次拿全，界面上要么都还没有、
/// 要么都对了。
class MeProfile {
  const MeProfile({required this.user, required this.creditAccount});

  final User user;
  final CreditAccount creditAccount;

  factory MeProfile.fromJson(Map<String, dynamic> json) => MeProfile(
        user: User.fromJson(json.asJsonMap(json['user'], field: 'user')),
        creditAccount: CreditAccount.fromJson(
          json.asJsonMap(json['credit_account'], field: 'credit_account'),
        ),
      );
}
