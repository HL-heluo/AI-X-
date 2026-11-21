import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/widgets/glass_tab_bar.dart';

import 'shell_harness.dart';

/// 阶段 0 的冒烟测试
///
/// 【什么是冒烟测试】
/// 不测细节，只回答一个问题：「这玩意儿还能不能启动？」
/// 通不过就说明有东西坏得很明显，不用往下查了。
///
/// 【为什么要写测试，新手不是应该先跑起来看吗】
/// 因为「跑起来看」靠眼睛，改一处忘一处；测试靠机器，每次改完跑一遍，
/// 它会告诉你有没有碰坏别的地方。等你项目到 5000 行时，这就是救命的东西。
///
/// 运行：flutter test
void main() {
  testWidgets('底部 4 个 Tab 都在，且点击能切换页面', (WidgetTester tester) async {
    // 把 App 渲染到测试环境里（这一步不会启动真机，纯粹是内存里画一遍）
    //
    // 【为什么不再直接 pump AppShell】见 `shell_harness.dart` 那段：
    // B5 之后「我的」页要读 provider，裸 pump 会因为缺 ProviderScope 直接抛。
    // 这个 helper 会先真注册一个账号，再渲染主界面。
    await pumpLoggedInShell(tester);

    // ── 1. 4 个 Tab 的文字都应该在 ──────────────────────
    //
    // 【为什么要限定在 Tab 栏里找】
    // AppShell 用的是 IndexedStack，它会把页面**全都建好**放在树里。
    // 而「作品」这个词既是 Tab 标签、又是作品页的占位标题，
    // 直接 find.text('作品') 会找到两个，断言就炸了。
    // 所以把查找范围收窄到 GlassTabBar 里面 —— 这样测的才是「Tab 栏上有什么」。
    final tabBar = find.byType(GlassTabBar);
    expect(
      find.descendant(of: tabBar, matching: find.text('创作')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: tabBar, matching: find.text('作品')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: tabBar, matching: find.text('交易')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: tabBar, matching: find.text('我的')),
      findsOneWidget,
    );

    // 【这一轮删掉了「课程」和「接单」】
    // 它们属于已被砍掉的业务（卖课程、接单抽佣）。变现方式只剩卖积分。
    expect(find.text('课程'), findsNothing);
    expect(find.text('接单'), findsNothing);

    // ── 2. 默认应该停在「创作」（下标 0）──────────────────
    //
    // 【注意】这里不去 find.text('开始创作') 判断当前页，
    // 因为 IndexedStack 会把页面全都建好放在树里，
    // 页面内容此时都能被找到 —— 找得到 ≠ 看得见。
    //
    // 所以直接检查 IndexedStack 的 index 属性，这才是真相。
    expect(currentIndex(tester), 0);

    // ── 3. 点「我的」，应该切到最后一项 ────────────────────
    await tester.tap(find.descendant(of: tabBar, matching: find.text('我的')));

    // pump 是「让界面刷新一帧」。
    // 因为切换 Tab 时有个 250ms 的颜色动画，用 pumpAndSettle 等它跑完。
    await tester.pumpAndSettle();

    expect(currentIndex(tester), 3);
    await unmountAndDrain(tester);
  });
}

/// 读取当前 IndexedStack 选中的下标 —— 也就是「现在在第几个 Tab」
int? currentIndex(WidgetTester tester) {
  return tester.widget<IndexedStack>(find.byType(IndexedStack)).index;
}
