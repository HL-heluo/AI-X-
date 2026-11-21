import '../models/me_profile.dart';

/// 当前用户的身份与积分总览（§12.1 `GET /me`）
abstract interface class MeRepository {
  /// 拉取用户信息 + 积分总览。
  ///
  /// 【为什么单单为它建一个 repository，看起来只包了一个接口】
  /// 因为它服务的是**全 App 最常被读的一份数据**：
  /// 首页右上角的积分胶囊、「我的」页的昵称和余额、积分页的总额，
  /// 三处都读它。而它是一次**单次拉取、没有状态机**的简单请求 ——
  /// 正好是验证「数据层通路是否打通」最干净的那块试金石。
  /// B5 的页面顺序建议就是先做「我的」页，正是这个道理。
  Future<MeProfile> fetchProfile();
}
