import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/format/credit_format.dart';
import '../../core/format/date_format.dart';
import '../../models/credit_account.dart';
import '../../models/me_profile.dart';
import '../../models/user.dart';
import '../../providers/me_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/async_section.dart';
import '../../widgets/glass_card.dart';
import '../../widgets/user_avatar.dart';

/// 个人中心（§13.2 的 `me`）
///
/// 【这一屏要回答三个问题】我是谁、我还有多少积分、我能去哪设置。
/// 顺序就是这个顺序 —— 身份在最上面，因为它是「这一屏说的是谁」的前提。
///
/// 【为什么积分卡片是可以点的入口，而不是把流水直接铺在这一屏】
/// 流水会长到几百条。铺在「我的」页里，滚动条会永远停在中间，
/// 而且「设置」会被顶到很远的地方去。分成独立一屏，各自有各自的长度。
///
/// 【为什么这一屏没有「充值」】§7.6 的充值档位明确标着「v3 预留」，
/// v1 只有注册赠送的积分。**不要顺手加充值入口** ——
/// 那会把一个「没有对手可以打的支付流程」写进代码。
class MePage extends ConsumerWidget {
  const MePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(meProfileProvider);
    final notifier = ref.read(meProfileProvider.notifier);

    return SafeArea(
      // bottom: false —— 底部是 Tab 栏，它自己会处理安全区，这里再让一次会多出一条空白
      bottom: false,
      child: RefreshIndicator(
        onRefresh: notifier.refresh,
        color: AppColors.sage,
        child: ListView(
          // 【为什么必须显式指定 AlwaysScrollable】内容不满一屏时，
          // ListView 默认不可滚（没有可滚的距离），RefreshIndicator 就**拉不动** ——
          // 用户会以为下拉刷新坏了。明明满屏时好好的，内容少时才失灵，最难查。
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(20, 22, 20, 28),
          children: [
            Text('个人中心', style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(height: 14),
            AsyncSection<MeProfile>(
              value: profile,
              onRetry: notifier.refresh,
              loading: const _MeSkeleton(),
              builder: (context, me) => _MeBody(profile: me),
            ),
          ],
        ),
      ),
    );
  }
}

/// 拿到数据后的「我的」内容。
class _MeBody extends StatelessWidget {
  const _MeBody({required this.profile});

  final MeProfile profile;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        GlassCard(
          padding: const EdgeInsets.all(18),
          child: _Identity(user: profile.user),
        ),
        const SizedBox(height: 14),
        _CreditCard(
          account: profile.creditAccount,
          onTap: () =>
              Navigator.of(context).push<void>(AppRoutes.creditsRoute<void>()),
        ),
        const SizedBox(height: 18),
        const _MenuCard(),
      ],
    );
  }
}

/// 头像 + 用户名 + 加入时间。
class _Identity extends StatelessWidget {
  const _Identity({required this.user});

  final User user;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        UserAvatar(name: user.username, size: 56),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                user.username,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w600,
                  color: AppColors.charcoal,
                ),
              ),
              // 注册时间可能拿不到（契约里 created_at 不是必返字段），
              // 拿不到就整行不显示 —— 写「加入于 」后面空着更像坏了。
              if (user.createdAt != null) ...[
                const SizedBox(height: 4),
                Text(
                  '加入于 ${formatDate(user.createdAt)}',
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.taupe,
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// 可用积分入口。
///
/// 【为什么这里显示「可用」而不是「总额」】可用 = 总额 − 冻结中。
/// 有任务在跑时被冻结的那部分**不能再用**，显示总额等于给用户
/// 一个他花不掉的数字 —— 他会发现自己「有 60 积分却下不了 40 的单」。
class _CreditCard extends StatelessWidget {
  const _CreditCard({required this.account, required this.onTap});

  final CreditAccount account;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.fromLTRB(18, 16, 12, 16),
      child: GestureDetector(
        key: const Key('me.credits'),
        onTap: onTap,
        // 【为什么是 opaque】卡片里大部分区域是空白。默认的
        // HitTestBehavior.deferToChild 只有在**落到具体子组件上**才算点击，
        // 用户点空白处会没反应 —— 明明整张卡看起来都可点。
        behavior: HitTestBehavior.opaque,
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '可用${CreditFormat.unit}',
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w500,
                      color: AppColors.taupe,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    // 拿不到余额时这里是「计算中…」而不是 0，见 CreditFormat.balanceText
                    CreditFormat.balanceText(account.available),
                    style: const TextStyle(
                      fontSize: 27,
                      fontWeight: FontWeight.w700,
                      color: AppColors.gold,
                      height: 1.1,
                    ),
                  ),
                  if (account.frozen > 0) ...[
                    const SizedBox(height: 6),
                    Text(
                      '冻结中 ${account.frozen} ${CreditFormat.unit}，任务结束后自动释放',
                      style: const TextStyle(
                        fontSize: 11.5,
                        color: AppColors.taupe,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const Icon(Icons.chevron_right, size: 20, color: AppColors.taupe),
          ],
        ),
      ),
    );
  }
}

/// 积分明细 / 设置 两个入口。
class _MenuCard extends StatelessWidget {
  const _MenuCard();

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          _MenuRow(
            key: const Key('me.ledger'),
            icon: Icons.receipt_long_outlined,
            label: '${CreditFormat.unit}明细',
            onTap: () =>
                Navigator.of(context)
                    .push<void>(AppRoutes.creditsRoute<void>()),
          ),
          // 【为什么分割线要缩进】让它从文字左侧开始，而不是从头贯通 ——
          // 通贯的线会把「图标 + 文字」这一行切断成两半的观感。
          const Divider(height: 1, indent: 62, endIndent: 16),
          _MenuRow(
            key: const Key('me.settings'),
            icon: Icons.settings_outlined,
            label: '设置',
            onTap: () =>
                Navigator.of(context)
                    .push<void>(AppRoutes.settingsRoute<void>()),
          ),
        ],
      ),
    );
  }
}

class _MenuRow extends StatelessWidget {
  const _MenuRow({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
        child: Row(
          children: [
            Container(
              width: 34,
              height: 34,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: AppColors.sageTint,
                borderRadius: BorderRadius.circular(AppRadius.lg),
              ),
              child: Icon(icon, size: 17, color: AppColors.sage),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w500,
                  color: AppColors.charcoal,
                ),
              ),
            ),
            const Icon(Icons.chevron_right, size: 20, color: AppColors.taupe),
          ],
        ),
      ),
    );
  }
}

/// 「我的」页的加载骨架：和真实内容同形（一个圆形头像 + 两行字 + 一张卡）。
///
/// 【为什么不让它用默认的几条灰线】默认骨架是「一段文字」的形状，
/// 而这一屏的第一眼是一个圆形头像。形状对不上，加载完成时会有一次明显的跳动。
class _MeSkeleton extends StatelessWidget {
  const _MeSkeleton();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            _block(width: 56, height: 56, radius: AppRadius.pill),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _block(width: 110, height: 15),
                  const SizedBox(height: 8),
                  _block(width: 78, height: 11),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 22),
        _block(height: 92),
        const SizedBox(height: 18),
        _block(height: 128),
      ],
    );
  }

  /// 一块灰色占位。宽度不传就是撑满。
  static Widget _block({
    double? width,
    required double height,
    double radius = AppRadius.lg,
  }) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: AppColors.sunken,
        borderRadius: BorderRadius.circular(radius),
      ),
    );
  }
}
