import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class GlassTabBar extends StatelessWidget {
  const GlassTabBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  final int currentIndex;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    final shape = BorderRadius.circular(AppRadius.hero);
    return SafeArea(
      top: false,
      minimum: const EdgeInsets.fromLTRB(12, 4, 12, 10),
      child: Align(
        heightFactor: 1,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: Colors.white,
              border: Border.all(color: AppColors.divider),
              borderRadius: shape,
              boxShadow: const [
                BoxShadow(
                  color: Color(0x1C22594A),
                  offset: Offset(0, 6),
                  blurRadius: 24,
                ),
              ],
            ),
            child: ClipRRect(
              borderRadius: shape,
              child: NavigationBar(
                height: 68,
                backgroundColor: Colors.transparent,
                selectedIndex: currentIndex,
                onDestinationSelected: onTap,
                destinations: const [
                  NavigationDestination(
                    key: Key('tab.0'),
                    icon: Icon(Icons.auto_awesome_outlined),
                    selectedIcon: Icon(Icons.auto_awesome),
                    label: '创作',
                  ),
                  NavigationDestination(
                    key: Key('tab.1'),
                    icon: Icon(Icons.grid_view_outlined),
                    selectedIcon: Icon(Icons.grid_view_rounded),
                    label: '作品',
                  ),
                  NavigationDestination(
                    key: Key('tab.2'),
                    icon: Icon(Icons.storefront_outlined),
                    selectedIcon: Icon(Icons.storefront_rounded),
                    label: '交易',
                    tooltip: '作品交易中心',
                  ),
                  NavigationDestination(
                    key: Key('tab.3'),
                    icon: Icon(Icons.person_outline),
                    selectedIcon: Icon(Icons.person),
                    label: '我的',
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
