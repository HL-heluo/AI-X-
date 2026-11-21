import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/env.dart';
import 'providers/app_providers.dart';

/// 程序的入口
///
/// 【前端类比】≈ 前端的 index.js / main.tsx：
/// 找到挂载点，把根组件渲染上去。
///
/// 【这一层为什么只干「把配置装进去」这一件事】
/// 因为 `main()` 是整个 App 唯一一个**允许直接 new 具体实现**的地方 ——
/// 别处一律走 `ref.watch`。所以「从环境读配置」这个副作用必须在这里发生，
/// 并且作为 override 注入 `ProviderScope`。
///
/// 这样做的直接好处是**测试**：测试起 `ProviderScope` 时不需要 override
/// 任何环境相关的东西（默认就是 Mock），也不会因为读到了真实环境变量
/// 而产生「本机跑得过、CI 跑不过」这种最烦人的差异。
void main() {
  runApp(
    ProviderScope(
      overrides: [
        // 从 --dart-define 读运行期配置（见 core/env.dart）。
        // 放在这里而不是在 provider 内部调用 fromEnvironment()，
        // 是为了让它**可被覆盖**：测试想注入一个「走真后端」的配置时，
        // 只要在 ProviderScope 里再 override 一次就行。
        //
        // 【为什么是 forApp 而不是 forTests】这两个工厂的机制一模一样，
        // 只差两个默认值：App 默认**连真后端**（本机 8000），
        // 测试默认 **Mock**（那 24 条 live 用例靠它 skip）。
        // 用错一个，裸跑就是「全假数据的界面」或者「一片连不上的红」。
        appConfigProvider.overrideWithValue(AppConfig.forApp()),
      ],
      child: const AiVideoApp(),
    ),
  );
}
