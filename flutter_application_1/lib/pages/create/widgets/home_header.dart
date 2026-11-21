import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../../../widgets/user_avatar.dart';

/// 首页顶部：问候语 + 积分入口 + 头像
///
/// 【前端类比】对应原型 `.home-header`：
/// 左边一列「小字 + 大字」，右边是胶囊和圆形头像。
///
/// 【这一轮把「L3」等级胶囊换成了积分入口】
/// 等级体系（创作者等级 / 经验 / 徽章）随「接单」业务一起砍掉了 ——
/// 它们的唯一目的是解锁更高等级的订单，订单没了它们就失去存在理由。
/// 而积分是新产品**唯一的货币**（充值买积分、用积分调 AI 能力），
/// 所以右上角这个位置留给「我还有多少积分」，点进去看余额与流水。
///
/// 【为什么没有积分数字时不显示 0】
/// 拿不到余额时显示一个具体数字，等于给用户一个可能不准的承诺。
/// 这里只显示「积分」两个字作为入口，等真实数值回来再补上。
class HomeHeader extends StatelessWidget {
  const HomeHeader({
    super.key,
    this.name,
    this.creditBalance,
    this.onCreditTap,
  });

  /// 当前登录用户的用户名。头像取它的首字。
  ///
  /// 【为什么可以为 null】资料还没拉回来时它确实是未知的。
  /// 那时头像退化成一个人形图标 —— **不编一个字母**。
  /// （B1 视觉阶段这里写死过一个 'K'：不管谁登录首页都显示 K。）
  final String? name;

  /// 可用积分。为 null 表示还没拿到（此时只显示入口，不显示数字）。
  ///
  /// 【为什么是「可用」不是「总」】可用余额 = 总余额 − 冻结中。
  /// 有任务在跑时，被冻结的那部分不能再用，所以头部显示可用余额更诚实。
  final int? creditBalance;

  /// 点击积分入口
  final VoidCallback? onCreditTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      // CSS: padding: 4px 0 20px
      padding: const EdgeInsets.only(top: 8, bottom: 24),
      child: Row(
        children: [
          Column(
            // Column 默认会把子元素横向拉伸，这里要让它按内容左对齐
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _greeting(),
                style: const TextStyle(fontSize: 12, color: AppColors.taupe),
              ),
              const SizedBox(height: 2),
              Text('开始创作', style: Theme.of(context).textTheme.headlineMedium),
            ],
          ),
          const Spacer(),
          _CreditPill(balance: creditBalance, onTap: onCreditTap),
          const SizedBox(width: 8),
          UserAvatar(name: name),
        ],
      ),
    );
  }

  /// 按当前时间挑问候语。
  ///
  /// 【为什么要算】原来这里写死「晚上好」，那意味着上午打开 App 也跟你说晚上好 ——
  /// 一句一眼假的问候，比没有问候更伤。既然这一轮本来就要改这个文件，顺手算对。
  static String _greeting() {
    final hour = DateTime.now().hour;
    if (hour < 6) return '夜深了，来点灵感';
    if (hour < 12) return '早上好，来点灵感';
    if (hour < 18) return '下午好，来点灵感';
    return '晚上好，来点灵感';
  }
}

/// 积分入口
///
/// 用香槟金：这个颜色在设计系统里本来就代表「积分 / 付费 / 值钱的信息」，
/// 换成积分体系后语义正好对得上，所以不用新增色值。
class _CreditPill extends StatelessWidget {
  const _CreditPill({this.balance, this.onTap});

  final int? balance;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: AppColors.goldSoft.withValues(alpha: 0.45),
          borderRadius: BorderRadius.circular(AppRadius.pill),
          border: Border.all(color: AppColors.goldSoft, width: 1),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.toll_outlined, size: 13, color: AppColors.gold),
            const SizedBox(width: 4),
            Text(
              // 拿不到余额时只作为入口出现，不编一个数字
              balance == null ? '积分' : '$balance 积分',
              style: const TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w600,
                color: AppColors.gold,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// 【B6 删掉了这里原来的私有 `_Avatar`】
//
// 它和 `widgets/user_avatar.dart` 长得一模一样，唯一的区别是里面的字
// 写死成了 'K' —— 不管谁登录，首页都显示 K。那是 B1 视觉阶段的占位。
//
// 现在直接用 `UserAvatar(name: ...)`：一份实现、一个出处，
// 换个人登录首页就跟着换字。`user_avatar.dart` 的注释里写了为什么
// B5 那一轮**故意**没有顺手改它（改它就得让首页去 watch 用户资料，
// 那是 B6 的活）。
