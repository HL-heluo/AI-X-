import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/core/constants/error_codes.dart';
import 'package:flutter_application_1/core/format/credit_format.dart';
import 'package:flutter_application_1/core/json_utils.dart';
import 'package:flutter_application_1/models/models.dart';

/// B2「契约冻结层」的验收测试
///
/// 【这批测试在防什么】
/// 它防的不是「代码写错了」，而是**契约漂移** ——
/// 有人顺手把状态字符串改了个名、把错误码删了一个、
/// 或者把算出来的「可用余额」改成了存下来的字段。
/// 这几类改动 `flutter analyze` 全都看不出来，但会直接导致
/// 线上「状态显示成排队中其实是失败」「余额和可用对不上」。
///
/// 【为什么要逐个断言枚举的字符串值，而不是只断言个数】
/// 只看个数（`values.length == 8`）的话，把 `canceled` 写成 `cancelled`
/// 测试照样绿 —— 而那正是 §0.4 术语锁定要防的头号问题。
/// 所以这里把**八个字面量一个一个列出来**，改动任何一个都必须先改测试，
/// 而改测试时会看到这段注释，知道要先去和后端确认。
void main() {
  group('TaskStatus · §11.3 的八个状态', () {
    test('八个状态一个不多一个不少', () {
      // 【文档笔误记录】§2 的文字说「只有 §11.3 定义的 7 个」，
      // 但 §11.3 实际列了 8 个。以 §11.3 的列表为准，8 个。
      expect(TaskStatus.values.length, 8);
    });

    test('每个状态的对外字符串逐字锁定', () {
      // ── 这八行就是和 backend 的契约 ──
      // 任何一行被改动，都意味着 App 与后端对不上了。
      expect(TaskStatus.pending.wire, 'pending');
      expect(TaskStatus.queued.wire, 'queued');
      expect(TaskStatus.submitted.wire, 'submitted');
      expect(TaskStatus.succeeded.wire, 'succeeded');
      expect(TaskStatus.failed.wire, 'failed');
      expect(TaskStatus.rejected.wire, 'rejected');
      // 特别注意：是 canceled（一个 l），不是 cancelled
      expect(TaskStatus.canceled.wire, 'canceled');
      expect(TaskStatus.expired.wire, 'expired');
    });

    test('八个 wire 值互不重复', () {
      // 防的是复制粘贴时忘了改字符串，导致两个状态指向同一个值
      final wires = TaskStatus.values.map((s) => s.wire).toSet();
      expect(wires.length, TaskStatus.values.length);
    });

    test('fromWire 能和 wire 来回转', () {
      for (final status in TaskStatus.values) {
        expect(TaskStatus.fromWire(status.wire), status);
      }
    });

    test('fromWire 遇到未知状态要抛异常，不能悄悄退化', () {
      // 【为什么不许给默认值】未知状态 = 后端加了新状态而前端不知道。
      // 悄悄当成 queued 会让线上出现「明明失败了却显示排队中」这种最难查的 bug。
      expect(() => TaskStatus.fromWire('processing'), throwsFormatException);
      expect(() => TaskStatus.fromWire(''), throwsFormatException);
      // 大小写不同也算不认识 —— 契约是大小写敏感的
      expect(() => TaskStatus.fromWire('SUCCEEDED'), throwsFormatException);
    });

    test('终态与进行中正好把八个状态分完', () {
      // 【这条为什么重要】轮询的停止条件就靠 isTerminal。
      // 漏标一个终态 = 一个永远转下去的定时器。
      const terminal = {
        TaskStatus.succeeded,
        TaskStatus.failed,
        TaskStatus.rejected,
        TaskStatus.canceled,
        TaskStatus.expired,
      };
      for (final status in TaskStatus.values) {
        expect(status.isTerminal, terminal.contains(status), reason: '$status');
        expect(status.isActive, !terminal.contains(status), reason: '$status');
      }
      // 两者必须互补且完整覆盖（防止将来加状态时忘了归类）
      expect(terminal.length + TaskStatus.values.where((s) => s.isActive).length,
          TaskStatus.values.length);
    });
  });

  group('ApiErrorCode · 错误码表', () {
    /// §12.3 那张表里**原样写着**的八个。
    ///
    /// 单独列出来是为了能和 `ApiErrorCode.values` 对集合 —— 见下面那条用例。
    const documented = <ApiErrorCode>{
      ApiErrorCode.insufficientCredits,
      ApiErrorCode.invalidPrompt,
      ApiErrorCode.imageTooLarge,
      ApiErrorCode.duplicateRequest,
      ApiErrorCode.rateLimited,
      ApiErrorCode.contentRejected,
      ApiErrorCode.providerError,
      ApiErrorCode.queueSaturated,
    };

    test('§12.3 表里的八个，字符串与 HTTP 状态码都对得上', () {
      expect(ApiErrorCode.insufficientCredits.wire, 'INSUFFICIENT_CREDITS');
      expect(ApiErrorCode.insufficientCredits.httpStatus, 400);

      expect(ApiErrorCode.invalidPrompt.wire, 'INVALID_PROMPT');
      expect(ApiErrorCode.invalidPrompt.httpStatus, 400);

      expect(ApiErrorCode.imageTooLarge.wire, 'IMAGE_TOO_LARGE');
      expect(ApiErrorCode.imageTooLarge.httpStatus, 400);

      expect(ApiErrorCode.duplicateRequest.wire, 'DUPLICATE_REQUEST');
      expect(ApiErrorCode.duplicateRequest.httpStatus, 409);

      expect(ApiErrorCode.rateLimited.wire, 'RATE_LIMITED');
      expect(ApiErrorCode.rateLimited.httpStatus, 429);

      expect(ApiErrorCode.contentRejected.wire, 'CONTENT_REJECTED');
      expect(ApiErrorCode.contentRejected.httpStatus, 422);

      expect(ApiErrorCode.providerError.wire, 'PROVIDER_ERROR');
      expect(ApiErrorCode.providerError.httpStatus, 502);

      expect(ApiErrorCode.queueSaturated.wire, 'QUEUE_SATURATED');
      expect(ApiErrorCode.queueSaturated.httpStatus, 503);
    });

    test('枚举 == §12.3 的八个 + 明确点名的追加项（多一个少一个都要红）', () {
      // ─────────────────────────────────────────────────────
      // 【为什么不是一句 `values.length == 8`】
      //
      // 那条守卫原本的写法是数长度。它的意思其实不是「必须是 8 个」，
      // 而是**「没人能悄悄往那张契约表里塞东西」** —— 数长度只是达到
      // 这个目的的一种（偷懒的）手段，而它有个洞：真要加码时，
      // 顺手把 8 改成 9，守卫就变成了摆设，之后再有人加第二个、
      // 第三个，同样是一句「改个数字」就过去了。
      //
      // 所以改成对**集合**：文档里的八个（`documented`）加上下面
      // 逐个点名的新增项，必须**不多不少**等于枚举本身。
      // 这样任何一次增删，无论有没有改这个数字，都会红 ——
      // 而红的这一刻，就是逼着人来这里写下「为什么加它」的时刻。
      // ─────────────────────────────────────────────────────
      const addedBeyondDoc = <ApiErrorCode>{
        // F8 加的：§6.1 说注册必须带邀请码，那「邀请码不对」就是
        // 注册路上必然会遇到的失败，而 §12.3 表里没有它 ——
        // 于是后端发的码前端认不出，注册页会说出那句撒谎的
        // 「连不上服务器，检查一下网络再试」。理由详见
        // `error_codes.dart` 里这条的注释。
        ApiErrorCode.inviteInvalid,
      };

      expect(
        ApiErrorCode.values.toSet(),
        documented.union(addedBeyondDoc),
        reason: '增删错误码必须同时改这个集合，并在注释里写明理由',
      );

      // 追加项本身也要按契约钉住，不然「点了名」但不校验值
      expect(ApiErrorCode.inviteInvalid.wire, 'INVITE_INVALID');
      expect(ApiErrorCode.inviteInvalid.httpStatus, 400);
    });

    test('每个错误码都有一句能直接给用户看的话', () {
      // 空文案 = 界面上会出现一片空白，比报错还糟
      for (final code in ApiErrorCode.values) {
        expect(code.defaultMessage, isNotEmpty, reason: '${code.wire} 没有兜底文案');
      }
    });

    test('tryFromWire 认不出时返回 null，而不是抛异常', () {
      // 【为什么错误码是宽松的、任务状态却是严格的】
      // 因为它们的失败代价不同：
      // 认不出错误码 → 退化成「出错了，请稍后重试」，用户还能继续用；
      // 认不出任务状态 → 界面根本不知道该画成什么，只能崩。
      // 所以一个宽容、一个严格，是有意为之。
      expect(ApiErrorCode.tryFromWire('RATE_LIMITED'), ApiErrorCode.rateLimited);
      expect(ApiErrorCode.tryFromWire('SOMETHING_NEW'), isNull);
      expect(ApiErrorCode.tryFromWire(null), isNull);
    });
  });

  group('CreditAccount · available 必须现算', () {
    test('available = balance − frozen', () {
      const account = CreditAccount(balance: 100, frozen: 40);
      expect(account.available, 60);
    });

    test('没有任务在跑时 available 等于 balance', () {
      const account = CreditAccount(balance: 20, frozen: 0);
      expect(account.available, 20);
    });

    test('available 是 getter 而不是字段 —— 改 balance 后立刻跟着变', () {
      // 【这条测的是「派生数据不要存」这条规矩有没有被违背】
      // 如果哪天有人把 available 改成构造参数传进来的字段，
      // 这个测试会红 —— 因为它会一直停在旧值上。
      const before = CreditAccount(balance: 100, frozen: 40);
      const after = CreditAccount(balance: 200, frozen: 40);
      expect(before.available, 60);
      expect(after.available, 160);
    });

    test('从 JSON 解析：20.0 这类整数形式的 double 也要收下', () {
      // 后端某天把 frozen 返回成 20.0（JSON 里就变成了 double），不能炸
      final account = CreditAccount.fromJson(<String, dynamic>{
        'balance': 100,
        'frozen': 20.0,
        'updated_at': '2026-10-12T08:30:00Z',
      });
      expect(account.balance, 100);
      expect(account.frozen, 20);
      expect(account.available, 80);
    });

    test('金额字段缺失要抛异常，不能静默当成 0', () {
      // 【为什么这条比别的都重要】少显示一个 0 只是难看，
      // 按错误金额记账是事故。所以金额一律 requireInt。
      expect(
        () => CreditAccount.fromJson(<String, dynamic>{'balance': 100}),
        throwsFormatException,
      );
    });
  });

  group('CreditFormat · §13.4 计费文案', () {
    test('还没问到价时显示「计算中…」', () {
      expect(CreditFormat.generationHint(null), '计算中…');
    });

    test('问到价后给的是区间 + 冻结说明，绝不出现定值承诺', () {
      const estimate =
          TaskCostEstimate(minCredits: 20, maxCredits: 25, freezeCredits: 25);
      final hint = CreditFormat.generationHint(estimate);

      expect(hint, '本次冻结 20~25 积分 · 按成片时长结算，多余自动退回');
      // 这三件事少任何一件，用户都会来问「钱去哪了」
      expect(hint, contains('冻结'));
      expect(hint, contains('按成片时长结算'));
      expect(hint, contains('多余自动退回'));
    });

    test('上下限相同时不写成 20~20', () {
      const estimate =
          TaskCostEstimate(minCredits: 20, maxCredits: 20, freezeCredits: 20);
      expect(estimate.isFixed, isTrue);
      expect(CreditFormat.costRange(estimate), '20');
    });

    test('【资金最重要的一个坑】冻结那行不能写成负数', () {
      // freeze 只是把「可用」搬进了「冻结」，余额根本没变。
      // 如果流水里画成 −40，用户会看到「冻结 −40」+「结算 −35」，
      // 以为自己被扣了 75。
      const freeze = CreditLedgerEntry(
        id: '1',
        kind: CreditLedgerKind.freeze,
        amount: 40,
      );
      expect(CreditFormat.ledgerAmountText(freeze), '冻结 40');
      expect(CreditFormat.ledgerAmountText(freeze), isNot(contains('-')));

      // 只有 settle 才是真的把钱花掉
      const settle = CreditLedgerEntry(
        id: '2',
        kind: CreditLedgerKind.settle,
        amount: 35,
      );
      expect(CreditFormat.ledgerAmountText(settle), '-35');

      const refund = CreditLedgerEntry(
        id: '3',
        kind: CreditLedgerKind.refund,
        amount: 5,
      );
      expect(CreditFormat.ledgerAmountText(refund), '+5');
    });

    test('余额拿不到时不能显示成 0（那是在撒谎）', () {
      expect(CreditFormat.balanceText(null), '计算中…');
      expect(CreditFormat.balanceText(0), '0');
      expect(CreditFormat.balanceWithUnit(null), '积分');
      expect(CreditFormat.balanceWithUnit(120), '120 积分');
    });
  });

  group('Task · 冻结 / 结算 / 退回', () {
    /// 一份和 §12.1 形状一致的、成功任务的最小样本
    Map<String, dynamic> succeededJson() => <String, dynamic>{
          'id': 42,
          'kind': 'image_to_video',
          'status': 'succeeded',
          'prompt': '一只猫在沙滩上奔跑',
          'params': {'ratio': '16:9', 'duration': 5},
          'freeze_amount': 40,
          'settled_amount': 35,
          'output_duration_sec': 7,
          'created_at': '2026-10-12T08:00:00Z',
          'finished_at': '2026-10-12T08:10:00Z',
        };

    test('解析成功任务：应退 = 冻结 − 实扣', () {
      final task = Task.fromJson(succeededJson());

      expect(task.id, '42');
      expect(task.kind, TaskKind.imageToVideo);
      expect(task.status, TaskStatus.succeeded);
      expect(task.freezeAmount, 40);
      expect(task.chargedAmount, 35);
      // 40 冻结、35 实扣 → 退回 5。这是「按实际成片时长结算」的核心算术。
      expect(task.refundAmount, 5);
      expect(task.isSettled, isTrue);
      expect(task.params.ratio, '16:9');
      expect(task.params.duration, 5);
      // 成片 7 秒 ≠ 下单时选的 5 秒 —— 这正是价格只能给区间的原因
      expect(task.outputDurationSec, 7);
    });

    test('结算后的文案要报出实扣和退回两个数', () {
      final task = Task.fromJson(succeededJson());
      expect(CreditFormat.settlementText(task), '本次消耗 35 积分，已退回 5 积分');
    });

    test('没有多冻结时就不提退回', () {
      final json = succeededJson()
        ..['settled_amount'] = 40
        ..['freeze_amount'] = 40;
      final task = Task.fromJson(json);
      expect(task.refundAmount, 0);
      expect(CreditFormat.settlementText(task), '本次消耗 40 积分');
    });

    test('失败任务全额退回，要明确说出来', () {
      final json = succeededJson()
        ..['status'] = 'failed'
        ..['settled_amount'] = 0
        ..['error_code'] = '50411'
        ..['error_msg'] = 'provider 超时';
      final task = Task.fromJson(json);

      expect(task.status, TaskStatus.failed);
      expect(task.refundAmount, 40);
      expect(task.errorCode, '50411');
      expect(CreditFormat.settlementText(task), '本次未消耗积分，已退回 40 积分');
    });

    test('任务还在跑时 settledAmount 是 null，不能当成 0', () {
      // 【为什么这个区分要紧】null 表示「还不知道最终扣多少」，
      // 0 表示「确实没扣」。混为一谈会让进行中的任务显示「已退回 40 积分」，
      // 用户会以为已经退钱了。
      final json = succeededJson()
        ..['status'] = 'submitted'
        ..remove('settled_amount')
        ..remove('finished_at');
      final task = Task.fromJson(json);

      expect(task.settledAmount, isNull);
      expect(task.isSettled, isFalse);
      expect(CreditFormat.settlementText(task), '已冻结 40 积分');
    });

    test('排队中的任务要能读到位次 —— 排队必须说实话', () {
      final json = succeededJson()
        ..['status'] = 'queued'
        ..['queue_position'] = 3
        ..remove('settled_amount');
      final task = Task.fromJson(json);
      expect(task.queuePosition, 3);
      expect(task.status.isActive, isTrue);
    });

    test('拿不到位次时应为 null，不能默认成 0', () {
      // 显示「前面还有 0 个」是在撒谎：用户会以为马上就到，
      // 实际上可能前面排着一堆没算出位次的任务。
      final json = succeededJson()..remove('queue_position');
      expect(Task.fromJson(json).queuePosition, isNull);
    });

    test('params 给成 JSON 字符串时也要能解析', () {
      // 后端 DB 里存的是 params_json 这一列，接口可能偷懒直接回传那根字符串
      final json = succeededJson()
        ..remove('params')
        ..['params_json'] = '{"ratio":"9:16","duration":10}';
      final task = Task.fromJson(json);
      expect(task.params.ratio, '9:16');
      expect(task.params.duration, 10);
    });

    test('lastTransitionAt 在没有 finished_at 时能往后退，不会变成 null', () {
      final json = succeededJson()
        ..['status'] = 'queued'
        ..remove('finished_at')
        ..remove('submitted_at');
      final task = Task.fromJson(json);
      expect(task.lastTransitionAt, isNotNull);
      expect(task.lastTransitionAt, task.createdAt);
    });
  });

  group('TaskCostEstimate · §12.1 的 {min, max, freeze}', () {
    test('映射 min / max / freeze 三个字段', () {
      final estimate = TaskCostEstimate.fromJson(<String, dynamic>{
        'min': 20,
        'max': 25,
        'freeze': 25,
      });
      expect(estimate.minCredits, 20);
      expect(estimate.maxCredits, 25);
      expect(estimate.freezeCredits, 25);
      expect(estimate.isFixed, isFalse);
    });

    test('缺字段就抛异常 —— 报价算错比报错更糟', () {
      expect(
        () => TaskCostEstimate.fromJson(<String, dynamic>{'min': 20}),
        throwsFormatException,
      );
    });
  });

  group('Asset · 只认永久 URL', () {
    test('解析资产，并区分视频与图片', () {
      final asset = Asset.fromJson(<String, dynamic>{
        'id': 7,
        'kind': 'video',
        'public_url': 'https://oss.example.com/a.mp4',
        'mime': 'video/mp4',
        'duration_sec': 7,
        'width': 1280,
        'height': 720,
        'is_ai_generated': true,
      });

      expect(asset.id, '7');
      expect(asset.kind, AssetKind.video);
      expect(asset.isVideo, isTrue);
      expect(asset.publicUrl, 'https://oss.example.com/a.mp4');
      expect(asset.aspectRatio, closeTo(1280 / 720, 0.0001));
    });

    test('缺 is_ai_generated 时默认按 true —— 合规标识宁可多打不能少打', () {
      final asset = Asset.fromJson(<String, dynamic>{
        'id': 8,
        'kind': 'image',
        'public_url': 'https://oss.example.com/a.png',
      });
      expect(asset.isAiGenerated, isTrue);
    });

    test('尺寸缺失时 aspectRatio 是 null，不许假装是方的', () {
      // 随便返回 1.0 会让竖屏视频被排版成正方形
      final asset = Asset.fromJson(<String, dynamic>{
        'id': 9,
        'kind': 'image',
        'public_url': 'https://oss.example.com/a.png',
      });
      expect(asset.aspectRatio, isNull);
    });
  });

  group('Paged · 分页', () {
    test('解析并判断还有没有下一页', () {
      final page = Paged.fromJson(<String, dynamic>{
        'items': [
          {'id': 1, 'kind': 'image', 'public_url': 'https://x/1.png'},
          {'id': 2, 'kind': 'image', 'public_url': 'https://x/2.png'},
        ],
        'page': 1,
        'page_size': 2,
        'total': 5,
      }, Asset.fromJson);

      expect(page.items.length, 2);
      expect(page.total, 5);
      expect(page.hasMore, isTrue); // 1×2 = 2 < 5
    });

    test('最后一页判定：已加载数达到总数就没有下一页', () {
      final page = Paged.fromJson(<String, dynamic>{
        'items': [
          {'id': 3, 'kind': 'image', 'public_url': 'https://x/3.png'},
          {'id': 4, 'kind': 'image', 'public_url': 'https://x/4.png'},
        ],
        'page': 2,
        'page_size': 2,
        'total': 4,
      }, Asset.fromJson);
      expect(page.hasMore, isFalse); // 2×2 = 4，正好到底
    });

    test('列表字段叫 list 时也要能读（§12.1 没规定名字）', () {
      final page = Paged.fromJson(<String, dynamic>{
        'list': [
          {'id': 5, 'kind': 'image', 'public_url': 'https://x/5.png'},
        ],
        'total': 1,
      }, Asset.fromJson);
      expect(page.items.length, 1);
      // 缺 page/page_size 时有默认值，不能炸
      expect(page.page, 1);
    });
  });

  group('json_utils · 解析的兜底行为', () {
    final json = <String, dynamic>{};

    test('整数形式的 double 收下', () {
      expect(json.asIntOrNull(20.0), 20);
      expect(json.asIntOrNull(20), 20);
    });

    test('真正的小数要抛异常，不能悄悄截断', () {
      // 积分和秒数都不该有小数。出现了说明契约理解错了，必须在开发期喊出来 ——
      // 悄悄截成 20 会让账目对不上。
      expect(() => json.asIntOrNull(20.5), throwsFormatException);
    });

    test('错误信息里要带字段名', () {
      // 【为什么专门测这个】`null as int` 报的错不告诉你是哪个字段，
      // 一个 15 字段的响应要逐行注释来找。带上名字才排得动。
      expect(
        () => json.requireInt(null, field: 'freeze_amount'),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            contains('freeze_amount'),
          ),
        ),
      );
    });

    test('时间统一转成 UTC', () {
      final utc = json.asDateTimeOrNull('2026-10-12T08:30:00Z');
      expect(utc!.isUtc, isTrue);
      // 带 +08:00 的写法也要落到同一个瞬间
      final offset = json.asDateTimeOrNull('2026-10-12T16:30:00+08:00');
      expect(offset, utc);
    });

    test('时间格式不认识要抛异常，不能给个 null 蒙混过去', () {
      expect(() => json.asDateTimeOrNull('昨天'), throwsFormatException);
    });

    test('布尔字段类型不对要抛异常', () {
      // `value == true` 这种偷懒写法会让 'true' 静默变成 false，
      // 而 is_ai_generated 是法律义务字段，静默为 false 等于合规标识不显示了
      expect(() => json.boolOr('true', false), throwsFormatException);
    });
  });

  group('术语锁定 · §2 不许出现同义词', () {
    test('枚举的对外字符串里没有别家业务的词', () {
      // 文档 §2 明确禁止拿同义词当标识符。这条测的是**契约字符串**，
      // 能拦住的典型错误是有人新增状态时顺手写成 'ORDER_FAILED'。
      final allWires = <String>[
        ...TaskStatus.values.map((e) => e.wire),
        ...ApiErrorCode.values.map((e) => e.wire),
        ...TaskKind.values.map((e) => e.wire),
        ...AssetKind.values.map((e) => e.wire),
        ...CreditLedgerKind.values.map((e) => e.wire),
      ].join(' ').toLowerCase();

      for (final banned in const ['order', 'job', 'material', 'coin', 'point']) {
        expect(allWires, isNot(contains(banned)), reason: '出现了被禁的同义词：$banned');
      }

      // 【注意 'credits' 不在被禁之列，这不是漏了】
      // `INSUFFICIENT_CREDITS` 里确实含 "credits"，但它是**后端定的契约字符串**，
      // 必须逐字照抄 —— §2 禁的是「代码里的名字」，不是「网络上的一根字符串」。
      // 同一条界限在 api_paths.dart 的 /credits/ledger 上也出现过一次。
      expect(ApiErrorCode.insufficientCredits.wire, contains('CREDITS'));
    });

    test('lib/ 的代码行里不许出现被禁的中文同义词', () {
      // 【为什么要扫源码而不是只扫枚举】因为真正会漂移的是普通业务代码：
      // 有人在页面里写 `Text('素材')`、或者把变量命名成 `订单列表`，
      // 枚举测试是看不见的。
      //
      // 【为什么跳过注释行】因为本项目用中文写大量讲解性注释，
      // 「产物 URL 只活 1 小时」这种句子是**正确的表达**，出现在说明里没有问题。
      // §2 管的是代码里怎么命名、界面上怎么用词，不是注释里怎么解释。
      const banned = ['算力', '点数', '订单', '素材', '产物'];
      final hits = <String>[];

      for (final entity in Directory('lib').listSync(recursive: true)) {
        if (entity is! File || !entity.path.endsWith('.dart')) continue;
        final lines = entity.readAsLinesSync();
        for (var i = 0; i < lines.length; i++) {
          final line = lines[i].trimLeft();
          // 跳过注释行（/// 文档注释、// 普通注释、* 续行）
          if (line.startsWith('//') || line.startsWith('*')) continue;
          for (final word in banned) {
            if (line.contains(word)) {
              hits.add('${entity.path}:${i + 1}  $word  ←  ${lines[i].trim()}');
            }
          }
        }
      }

      expect(hits, isEmpty, reason: 'lib/ 里出现被禁的同义词（§2 术语锁定）：\n${hits.join('\n')}');
    });
  });
}
