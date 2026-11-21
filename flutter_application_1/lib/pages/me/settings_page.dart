import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants/app_info.dart';
import '../../providers/auth_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_background.dart';
import '../../widgets/glass_card.dart';

/// 设置（§13.2 的 `settings`）
///
/// 【这一屏现在只有两件事】关于、退出登录。
/// 这是**故意留白**的：文件里没有的东西，比文件里写了一半的东西安全。
///
/// 【为什么「清缓存」「通知开关」「清除数据」这些都没做】
/// 它们各自都要有对应的真实机制（本地缓存目录、通知权限、账号注销流程），
/// 现在放上去只能是不起作用的开关 —— 用户拨了一下发现没变化，
/// 比没有这个开关更伤信任。
class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return AppBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(title: const Text('设置')),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
          children: [
            const _AboutCard(),
            const SizedBox(height: 18),
            _LogoutCard(onLogout: () => _confirmLogout(context, ref)),
          ],
        ),
      ),
    );
  }

  /// 退出登录：**先问一句，再登出**。
  ///
  /// 【为什么值得为这一步多做一次交互】退出登录是这一屏唯一一个
  /// **不可撤销**的动作 —— 点了之后 token 就没了，而 v1 的账号体系里
  /// 用户要重新输密码（还没有「记住我」之外的任何恢复手段）。
  /// 一次确认的成本远低于一次误触。
  ///
  /// 【为什么确认框里的按钮写「退出登录」而不是「确定」】
  /// 确认框的意义在于让人**在按下去之前读一遍自己要做什么**。
  /// 「确定」两个字什么都没说，用户是靠肌肉记忆点的。
  Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
    // 【先把 notifier 抓在手里，别在 await 之后再用 ref】
    // 登出会让整棵界面树重建（见 `app.dart` 里 MaterialApp 的 key 注释），
    // 这一页会被销毁。await 之后再碰 ref / context 就是在碰一个已经没了的元素。
    final auth = ref.read(authControllerProvider.notifier);

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.bgWarm,
        title: const Text('退出登录', style: TextStyle(fontSize: 17)),
        content: const Text(
          '退出后需要重新输入用户名和密码才能进来。',
          style: TextStyle(fontSize: 13.5, height: 1.5, color: AppColors.textBody),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text(
              '取消',
              style: TextStyle(fontSize: 14, color: AppColors.taupe),
            ),
          ),
          TextButton(
            key: const Key('settings.logout.confirm'),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text(
              '退出',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: AppColors.danger,
              ),
            ),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    // 【这里没有一行导航】登出之后 `app.dart` 会把 home 换成登录页，
    // 并且因为登录态变了会**连 Navigator 一起重建**（见那段 key 的注释），
    // 所以压在栈上的这一页会跟着消失 —— 不需要也不该在这里 pop。
    await auth.logout();
  }
}

/// 关于：产品名、版本号、内测标识。
class _AboutCard extends StatelessWidget {
  const _AboutCard();

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  AppInfo.appTitle,
                  style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                    color: AppColors.charcoal,
                  ),
                ),
              ),
              // 产品名还没定（§18-5），如实标出来 ——
              // 内测用户看到这句话，就不会把这个名字当成品牌去传播。
              if (AppInfo.isPlaceholderName) const _BetaTag(),
            ],
          ),
          const SizedBox(height: 14),
          const Divider(height: 1),
          const SizedBox(height: 12),
          _InfoRow(label: '版本', value: AppInfo.version),
        ],
      ),
    );
  }
}

/// 「内测中」小标签。
class _BetaTag extends StatelessWidget {
  const _BetaTag();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: AppColors.sageTint,
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: const Text(
        '内测中',
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: AppColors.sage,
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: const TextStyle(fontSize: 13.5, color: AppColors.textBody),
          ),
        ),
        Text(
          value,
          style: const TextStyle(fontSize: 13.5, color: AppColors.taupe),
        ),
      ],
    );
  }
}

/// 退出登录。单独一张卡、单独一个颜色 —— 它是这一屏唯一的破坏性动作。
class _LogoutCard extends StatelessWidget {
  const _LogoutCard({required this.onLogout});

  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: EdgeInsets.zero,
      child: GestureDetector(
        key: const Key('settings.logout'),
        onTap: onLogout,
        behavior: HitTestBehavior.opaque,
        child: const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.logout, size: 17, color: AppColors.danger),
              SizedBox(width: 8),
              Text(
                '退出登录',
                style: TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w600,
                  color: AppColors.danger,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
