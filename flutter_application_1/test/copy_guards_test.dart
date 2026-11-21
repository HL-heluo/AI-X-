import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/core/constants/app_info.dart';
import 'package:flutter_application_1/core/env.dart';

/// ─────────────────────────────────────────────────────────
/// B7 的「防回归」测试：**守的不是功能，是纪律**
///
/// 这个文件里的每一条，测的都是「以后有人顺手改一下就会出事」的地方。
/// 它们跑起来很快（只读文件、比字符串），代价几乎为零 ——
/// 而它们挡住的那类错误，靠人盯代码是盯不住的：
/// 一个措辞、一个产品名、一句计费承诺，任何一处漏改都不会报错，
/// 只会静悄悄地变成一次投诉或一次违规。
///
/// 【为什么不用 analyze 的自定义规则】那需要额外依赖和一台配置好的机器；
/// 一个 `test/` 里的普通用例，任何人 clone 下来 `flutter test` 就能跑。
/// ─────────────────────────────────────────────────────────

/// 把一个 .dart 文件读成「非注释行」。
///
/// 【为什么跳过注释行】这个项目的注释是中文长文，里面会大量**引用**
/// 那些被禁的措辞（比如解释「为什么不能写『预计消耗』」）。
/// 那些句子是对的 —— 要拦的是**代码和界面文案**里出现它们。
/// 同一条规矩在 `models_test.dart` 的术语测试里也是这么处理的。
List<({int line, String text})> codeLines(String path) {
  final file = File(path);
  if (!file.existsSync()) return const [];

  final result = <({int line, String text})>[];
  final lines = file.readAsLinesSync();
  for (var i = 0; i < lines.length; i++) {
    final trimmed = lines[i].trimLeft();
    // /// 文档注释、// 普通注释、* 续行、以及 HTML 注释里的正文
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) continue;
    result.add((line: i + 1, text: lines[i]));
  }
  return result;
}

/// 遍历 lib/ 下所有 .dart 文件。
Iterable<File> allLibFiles() {
  return Directory('lib').listSync(recursive: true).whereType<File>().where(
        (f) => f.path.endsWith('.dart'),
      );
}

void main() {
  group('计费文案的底线（§13.4）', () {
    test('lib/ 里不许出现「确定会花多少钱」的措辞', () {
      // 【为什么这条是法律/投诉级别的】
      // 视频的实际时长由 provider 侧的 Agent 决定，下单那一刻**连后端都不知道**
      // 最终会扣多少。所以任何「预计消耗 N 积分」都是一个注定不准的承诺，
      // 而用户对「说好 20 扣了 21」的容忍度极低。
      //
      // 这条测试扫的是**字面量**：它能拦住「有人新写了一句预计消耗」，
      // 拦不住「有人用拼接拼出来一句」——后者只能靠 code review。
      // 但按经验，出问题的就是那种顺手写一句的情况。
      const banned = [
        '预计消耗',
        '预计花费',
        '预估消耗',
        '预计扣除',
        '将消耗',
      ];

      final hits = <String>[];
      for (final file in allLibFiles()) {
        for (final line in codeLines(file.path)) {
          for (final word in banned) {
            if (line.text.contains(word)) {
              hits.add('${file.path}:${line.line}  $word  ←  ${line.text.trim()}');
            }
          }
        }
      }

      expect(
        hits,
        isEmpty,
        reason: '生成按钮下不许写确定的积分数字（§13.4）：\n${hits.join('\n')}',
      );
    });

    test('计费文案只有 credit_format.dart 一个出处', () {
      // 【为什么要扫这个】这三句话要在四个地方显示（首页按钮下、图片生成页、
      // 视频生成页、参数胶囊）。任何一处自己抄一份字符串，
      // 就会开始漂移成四种说法 —— 而「预计消耗」那条禁令只能扫字面量，
      // 拼出来的话它扫不到。
      const phrases = ['计算中…', '本次冻结', '按成片时长结算', '多余自动退回'];

      /// 唯一允许出现这些字面量的文件。
      ///
      /// 【为什么 mock 也在白名单里】`fake_api_client.dart` 里有一句
      /// `note: '按成片时长结算'` —— 那是**假服务端返回的流水备注**，
      /// 相当于真后端返回的一根字符串，不是界面文案。
      const allowed = {
        'lib/core/format/credit_format.dart',
        'lib/data/mock/fake_api_client.dart',
      };

      final hits = <String>[];
      for (final file in allLibFiles()) {
        if (allowed.contains(file.path.replaceAll(r'\', '/'))) continue;
        for (final line in codeLines(file.path)) {
          for (final phrase in phrases) {
            if (line.text.contains(phrase)) {
              hits.add(
                '${file.path}:${line.line}  $phrase  ←  ${line.text.trim()}',
              );
            }
          }
        }
      }

      expect(
        hits,
        isEmpty,
        reason:
            '计费文案要取 CreditFormat 的常量，不要各写一份：\n${hits.join('\n')}',
      );
    });
  });

  group('站内积分交易的文案边界', () {
    // 【这条是怎么来的】不是先想出来再去找问题，而是**反过来的**：
    // B7 把 Web 产物真的在浏览器里走了一遍，走到「积分不足」那一步，
    // 错误条上写着「积分不足，**请先充值**」——
    // 而 v1 的积分页连一个充值入口都没有（§7.6 的档位是 v3 预留，
    // `me_credits_test.dart` 里专门有一条守这个）。
    //
    // 也就是说：界面上出现了一个「去点一个不存在的东西」的指引。
    // 这类问题有共同点 —— **代码全都跑得通、测试全绿**，
    // 只有把画面看一眼才发现。所以把它变成一条会红的测试。
    //
    // 作品交易页可以使用「购买」，表单和确认弹窗会说明以 VCR 积分成交。
    test('作品交易页使用购买文案，全站保留充值和现金支付用语守卫', () {
      const banned = ['充值', '支付', '购买'];

      final hits = <String>[];
      for (final file in allLibFiles()) {
        final marketPage = file.path.replaceAll('\\', '/')
            .contains('lib/pages/marketplace/');
        for (final line in codeLines(file.path)) {
          for (final word in banned) {
            if (line.text.contains(word) && !(word == '购买' && marketPage)) {
              hits.add('${file.path}:${line.line}  $word  ←  ${line.text.trim()}');
            }
          }
        }
      }

      expect(
        hits,
        isEmpty,
        reason:
            '站内积分市场的文案越界：\n${hits.join('\n')}\n'
            '（注释里解释「为什么没有充值」是允许的，这条只扫非注释行）',
      );
    });
  });

  group('产品名的四个出处', () {
    // 【为什么产品名要测】它散落在 Dart、两个 web 文件、一个原生清单里，
    // 那里读不到 Dart 常量，只能手工同步。改了一边忘了另一边**不会报错** ——
    // 只会出现「浏览器标签页还写着 flutter_application_1」这种
    // 「这项目还没做完」的观感，而它通常一直不会被发现。
    //
    // 【为什么只比"包含"而不是全等】各处会带自己的修饰：
    // index.html 的 <title> 就是纯名字，manifest 的 description 是一句话 ——
    // 它们只要**包含**这个名字就够了。
    test('Dart / web / Android 三处用的是同一个名字', () {
      final checks = <String, String>{
        'web/index.html': AppInfo.appTitle,
        'web/manifest.json': AppInfo.appTitle,
        'android/app/src/main/AndroidManifest.xml': AppInfo.appTitle,
      };

      final missing = <String>[];
      for (final entry in checks.entries) {
        final file = File(entry.key);
        // 【为什么要断言文件存在】路径写错时 readAsStringSync 会抛异常，
        // 那看起来像「测试挂了」，而不像「这个文件不见了」。
        expect(file.existsSync(), isTrue, reason: '找不到 ${entry.key}');
        final content = file.readAsStringSync();
        if (!content.contains(entry.value)) missing.add(entry.key);
      }

      expect(
        missing,
        isEmpty,
        reason:
            '这些文件里的产品名和 AppInfo.appTitle（${AppInfo.appTitle}）不一致：\n'
            '${missing.join('\n')}\n'
            '（原生清单和 HTML 读不到 Dart 常量，只能手工同步 —— 这正是这条测试存在的理由）',
      );
    });

    test('旧名字已经清干净了', () {
      // 【这条守的是「别把作废的业务名捞回来」】"flutter_application_1" 是
      // `flutter create` 的默认名，用户能在**三个地方**看见它：
      // 浏览器标签页、装到桌面上之后的图标名、以及 iOS 的桌面名。
      // 「AI 聚合平台」是作废的电商业务名，留着它会让新同事以为这还是个电商项目。
      final stale = ['flutter_application_1', 'AI 聚合平台'];

      final hits = <String>[];
      for (final path in const [
        'web/index.html',
        'web/manifest.json',
        'android/app/src/main/AndroidManifest.xml',
      ]) {
        final content = File(path).readAsStringSync();
        for (final word in stale) {
          if (content.contains(word)) hits.add('$path  ←  $word');
        }
      }

      // 【为什么 pubspec.yaml 不在这个名单里】它的 `name:` 是**包名**，
      // 决定的是 `import 'package:flutter_application_1/...'` 这一行，
      // 改它要动全项目每一处 import —— 而它不会出现在任何界面里。
      // 这是刻意的取舍，不是漏了。
      expect(hits, isEmpty, reason: '还挂着旧名字：\n${hits.join('\n')}');
    });
  });

  /// ─────────────────────────────────────────────────────────
  /// 「裸跑连的是谁」—— 2026-10-17 翻过一次，别再翻回去
  ///
  /// 【为什么这一组值得存在】这两个默认值**不会报错，只会静静地换一个世界**：
  /// App 的默认翻回 Mock，症状是「界面全对、数据全假」（这一路上最难当场
  /// 发现的一类错，真被咬过）；测试的默认翻成真后端，症状更重 ——
  /// 裸跑 `flutter test` 会去打真后端，而那 24 条 live 用例**每个用例前都清库**。
  ///
  /// 它和这个文件里别的条目同类：代码全都跑得通、别的测试全绿，
  /// 只有把「什么都没传时会怎样」想一遍才发现。所以把它变成会红的测试。
  /// ─────────────────────────────────────────────────────────
  group('默认连谁（§12 翻过一次，方向别再翻回去）', () {
    test('App 不传参数时连的是真后端', () {
      // 【为什么这条能在测试里直接断】因为 `forApp()` 每次调用都真的去读
      // 编译期参数，而**裸跑 `flutter test` 时那些参数就是没给的** ——
      // 于是这里算出来的正是「用户双击图标时会发生什么」。
      //
      // 【它什么时候会红】有人把 forApp 的默认翻回 `true`（也就是
      // 「忘带参数 = 全假数据的界面」那个旧世界）。
      //
      // 【它在 live 门禁下不会假红】门禁里 `USE_MOCK=false` 是**显式给的**，
      // forApp 读到的还是 false —— 两种世界下这条断言都成立，
      // 而它真正要挡的那次改动只会在裸跑时暴露。
      final app = AppConfig.forApp();
      expect(
        app.useMock,
        isFalse,
        reason: 'App 默认必须连真后端 —— 默认 Mock 的症状是「界面全对、'
            '数据全假」，而它看起来和真的完全一样（见 env.dart 的类注释）。'
            '要让某次运行走 Mock，显式传 --dart-define=USE_MOCK=true。',
      );
      expect(
        app.baseUrl,
        isNotEmpty,
        reason: '走真后端却没有地址 → env.dart 的快速失败会直接 StateError，'
            '裸跑应该是「能跑起来」的',
      );
    });

    test('测试不传参数时**仍然**走 Mock', () {
      // 【为什么这一条只能读源码】因为要断的是「命令行什么都没给」这一种世界，
      // 而**测试进程自己就是带着参数编译出来的** —— 它没法伪造一个
      // 「没给参数」的世界来调 `forTests()`。能观测到的只有「这次运行实际
      // 拿到了什么」，那是个同义反复，永远不会红。
      //
      // 所以守源头：把 `forTests` 那个工厂体切出来，看它的 defaultValue。
      final body = _factoryBody('forTests');

      expect(
        body,
        contains("bool.fromEnvironment('USE_MOCK', defaultValue: true)"),
        reason: '测试的默认必须仍然是 Mock。裸跑 flutter test 去打真后端，'
            '不只是「连不上」——那 24 条 live 用例每个用例前都清库，'
            '一旦本机正好起着后端，一次普通的单元测试就会把真库清掉。',
      );
      // 【为什么顺带钉住「不留地址」】`USE_MOCK=false` 却没给 API_BASE_URL
      // 时那条 StateError 是 live 门禁的护栏（见 live_backend.dart 的注释）。
      // 给 forTests 补一个地址默认值，就会把它变成「静默连了个别的东西」。
      expect(
        body.split('defaultValue:').length - 1,
        1,
        reason: 'forTests 里只该有一个 defaultValue（USE_MOCK 那个）—— '
            '再补一个 API_BASE_URL 的默认值，live 门禁那条快速失败就废了。',
      );
    });
  });
}

/// 把 `lib/core/env.dart` 里某个工厂的源码切出来，空白压成单空格。
///
/// 【为什么按 `factory`/`static` 关键字切】工厂体里有嵌套括号和闭包，
/// 数括号会数错；而这两个关键字恰好是「下一个成员开始」的可靠标志。
String _factoryBody(String name) {
  final src = File('lib/core/env.dart').readAsStringSync();
  final match = RegExp(
    'factory AppConfig\\.$name\\(\\)(.*?)(?=\\n  (?:factory|static) )',
    dotAll: true,
  ).firstMatch(src);

  // 【为什么要断言找到了】正则写歪时 firstMatch 返回 null，
  // 那看起来像「测试挂了」，而不像「这个工厂不见了 / 改名了」。
  expect(match, isNotNull, reason: 'env.dart 里找不到 factory AppConfig.$name()');

  return match!.group(1)!.replaceAll(RegExp(r'\s+'), ' ');
}
