import '../../core/constants/api_paths.dart';
import '../../core/constants/error_codes.dart';
import '../../core/constants/task_status.dart';
import '../../core/network/api_client.dart';
import '../../core/network/api_exception.dart';
import '../../models/task.dart';

// ═══════════════════════════════════════════════════════════════════
//  §7.1 定价表（1 积分 = ¥0.10），从真实成本反推出来的，不是拍脑袋
// ═══════════════════════════════════════════════════════════════════
//
//  | 动作             | 平台成本 | 定价          |
//  | 文生图 ×1        | ¥0.20    | 4 积分        |
//  | 视频 720P ×1 秒  | ¥0.28    | 4 积分/秒     |
//  | 视频 1080P ×1 秒 | ¥0.63    | 9 积分/秒     |
//
//  换算直觉：4 积分 = 1 张图 = 1 秒 720P 视频。
//
//  【为什么这些数字必须住在 Mock 里，而不是抽成一份「前端定价表」】
//  因为定价是**服务端的事**。App 从来不该自己算钱 ——
//  它只调 `GET /generation/cost` 问价。这里放一份，是因为
//  FakeApiClient 演的就是服务端本人。
//  哪天有人在 App 里 import 这些常量去算价格，那就是把定价逻辑泄漏到了客户端，
//  接真后端时立刻会不一致。

/// 文生图固定 4 积分（成本固定，冻结额 = 结算额）。
const int _creditsPerImage = 4;

/// 720P 视频每秒 4 积分。
///
/// 【为什么只有 720P 一个常量】§14.1 定了 v1 先上 720P，
/// 而 §18-2 说 provider 的 1080P 实际能力还没确认 ——
/// 定价表里的 1080P（9 积分/秒）暂时用不上，等 C1 卡实测完再开。
/// 现在就摆一个用不到的常量，只会让「到底支持哪几档」变得含糊。
const int _creditsPerSecond720 = 4;

/// 注册赠送（§12.1）。
///
/// 【为什么从 20 改成了 50】原值是 20，但视频要按「请求时长 + 3 秒余量」冻结
/// （§7.2），5 秒的就要冻 32 —— 20 < 32，于是**每个新用户第一次做视频必然撞墙**，
/// 而 v1 没有充值入口（§7.6）。§15.1 的验收剧本早就写着「注册后发 50 积分」，
/// 等于剧本自己承认了要补钱。
///
/// 现在把赠送提到 50（= §15.1 剧本的起步额），死路从「第一次」退到「第二次」：
/// 一图（4）+ 一视频（结算 24）后剩 22 < 32，第二次做视频仍然会撞墙，
/// 但用户至少完整跑通过一轮。**那条死路没有被藏起来，只是挪后了一步** ——
/// 「积分不足」的文案、出口和测试都还在。真正解决它要靠 v3 的充值（§7.6）。
///
/// 【⚠️ 这是一个契约值】改它必须前后端一起改（§12.1），
/// 而且会牵动 §15.1 的验收算式（余额 = 50 − 实际消耗）。
const int _signupGrant = 50;

/// 每日任务数上限（§7.5 第 3 道闸，文档建议 20，可配）。
const int _dailyTaskLimit = 20;

/// 每用户「同时进行的任务数」上限（§8.2 闸门值，默认 1）。
///
/// 【注意 §8.2 特别强调「图与视频分开计数」】
/// 因为图片是秒级完成、视频要十分钟。如果混在一个闸门里，
/// 用户排了个视频之后，连图都生成不了 —— 图片会被视频饿死。
/// 所以下面是**按 kind 各算各的**。
const int _maxConcurrentPerKind = 1;

/// 冻结时在「请求时长」之上预留的秒数。
///
/// 【⚠️ 这是一个占位值，需要与后端确认】
/// §7.2 只说 `freeze = ceil((输入视频时长 + 请求时长上限) × 每秒单价)`，
/// 但没定义「请求时长上限」到底比用户选的时长高多少 ——
/// 因为 provider 侧的 Agent 自主决定成片时长（官方原话「可能与目标值存在偏差」）。
/// 这里先按「多留 3 秒」实现，让冻结额略高于预估上限。
/// 真实的偏差幅度要等 C1 卡（即梦接入 Spike）实测出来才能定死。
const int _durationSlackSec = 3;

/// 提示词长度上限（§11.2：≤2000 字，提交前校验）。
const int _maxPromptLength = 2000;

/// 参考图大小上限（§9.4 对齐 provider 限制：≤20MB）。
const int _maxImageBytes = 20 * 1024 * 1024;

// ═══════════════════════════════════════════════════════════════════
//  Mock 服务端
// ═══════════════════════════════════════════════════════════════════

/// 本地假后端
///
/// 实现 [ApiClient]，返回**与 §12.1 契约逐字一致**的 JSON。
/// 它是「后端还没写」这段时间里，App 唯一的数据来源。
///
/// ─────────────────────────────────────────────────────────
/// 【它「极简」在哪，又「不极简」在哪】
///
/// 极简的部分（用户选定的取舍）：
///   * 默认任务提交后**立刻成功**，不经过 queued / submitted；
///   * 不注入错误、不模拟网络延迟、不退避重试；
///   * 数据全在内存，进程一退就没了。
///
/// **一点也不简的部分** —— 这三件是**契约**，不是 UX 保真，缩水了就白做：
///   1. **幂等键去重**（§7.5 第 2 道闸）：同一个 key 再提交返回 409，
///      而不是又建一个任务。这是防连点双扣的闸门，写错了会真的扣两次钱。
///   2. **冻结 → 结算 → 退回的真实算术**（§7.2）：冻结额、结算额、
///      退回额三个数必须**真的算**并三笔入账。随便返回成功的话，
///      接真后端那天账目对不上，而你根本不知道是哪一层算错了。
///   3. **配额真抛 RATE_LIMITED**（§7.5 第 3 道闸）：每日 ≤ 20、
///      每类同时 ≤ 1。不抛的话，UI 里那些「已达今日上限」的分支
///      永远没被执行过，上线才发现它们写错了。
/// ─────────────────────────────────────────────────────────
class FakeApiClient implements ApiClient {
  FakeApiClient({
    this.latency,
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now;

  /// 一个任务在**每个阶段**停留多久。
  ///
  /// null（默认）= 极简模式，提交后立刻成功。
  /// 非 null = 走真实状态机 `queued` →（latency）→ `submitted` →（再 latency）→ `succeeded`。
  ///
  /// 开了它，文档里这几条才能人工验收：排队位次、轮询退避、
  /// 「关掉 App 再打开进行中任务还在」、完成通知。
  final Duration? latency;

  /// 时钟。测试可以注入一个假时钟，免得真的 sleep 几十秒。
  final DateTime Function() _clock;

  // ── 模拟服务端的状态 ──────────────────────────────────────

  final Map<String, _FakeUser> _usersByUsername = {};
  final Map<String, _FakeUser> _usersById = {};

  /// token → userId。
  final Map<String, String> _userIdByToken = {};

  /// 当前登录的 token。
  ///
  /// 【为什么 Mock 要自己记着这个】
  /// 真实实现（DioApiClient）的 token 是由拦截器从 TokenStore 取出来塞进
  /// Authorization 头的，ApiClient 接口本身看不到它。Mock 没有「头」这个概念，
  /// 所以只能自己记一份「最近一次登录发出去的 token 是谁的」。
  /// 效果上等价：**没登录就 401**，登录过期也能演。
  String? _currentToken;

  final Map<String, _FakeAccount> _accounts = {};
  final List<Map<String, dynamic>> _ledger = [];
  final List<_FakeTask> _tasks = [];
  final List<Map<String, dynamic>> _assets = [];

  /// 幂等键 → 任务 id。这就是 §7.5 第 2 道闸的实体。
  final Map<String, int> _taskIdByIdempotencyKey = {};

  int _nextId = 1000;

  // ═══════════════════════════════════════════════════════════
  //  ApiClient 实现
  // ═══════════════════════════════════════════════════════════

  @override
  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    // 【为什么每个请求进来先推进一次】因为「状态只在服务端变」——
    // 客户端只能通过请求看到变化。真实后端由 worker 在后台推进，
    // Mock 没有后台线程，就退而求其次：**你来看的时候，它才往前走**。
    _advance();

    final seg = _segments(path);

    if (path == ApiPaths.me) return _me();
    if (path == ApiPaths.creditLedger) return _ledgerPage(query);
    // 影子链：Mock 环境没有链，返回 enabled=false，页面显示「未开启链上映射」
    if (path == ApiPaths.creditChain) {
      return <String, dynamic>{
        'enabled': false,
        'rpc': '',
        'contract': null,
        'address': null,
        'on_chain_balance': null,
        'ledger_balance': 0,
        'total_supply': null,
        'recent_ops': <Object>[],
      };
    }
    if (path == ApiPaths.generationCost) return _costEstimate(query);
    if (path == ApiPaths.tasks) return _taskList(query);
    if (path == ApiPaths.assets) return _assetPage(query);
    if (seg.length == 3 && seg.first == 'assets' && seg.last == 'evidence') {
      _requireUserId();
      return {'status': 'disabled'};
    }

    // /tasks/{id}
    if (seg.length == 2 && seg.first == 'tasks') {
      final task = _taskDetail(seg.last);
      return task.toJson(queuePosition: _queuePositionOf(task));
    }

    throw _notImplemented('GET', path);
  }

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body}) async {
    _advance();
    final json = _body(body);
    final seg = _segments(path);

    if (path == ApiPaths.register) return _register(json);
    if (path == ApiPaths.login) return _login(json);

    if (path == ApiPaths.uploadImage) {
      throw _notImplemented('POST', path);
    }

    if (path == ApiPaths.generateImage) return _submitImage(json);
    if (path == ApiPaths.generateVideo) return _submitVideo(json);

    // /tasks/{id}/cancel
    if (seg.length == 3 && seg.first == 'tasks' && seg.last == 'cancel') {
      return _cancelTask(seg[1]);
    }

    throw _notImplemented('POST', path);
  }

  @override
  Future<Map<String, dynamic>> delete(String path) async {
    _advance();
    final seg = _segments(path);

    // /assets/{id}
    if (seg.length == 2 && seg.first == 'assets') {
      final userId = _requireUserId();
      final id = _parseId(seg.last, what: '资产');
      final before = _assets.length;
      _assets.removeWhere(
        (a) => a['id'] == id && a['user_id'] == userId,
      );
      if (_assets.length == before) {
        throw AppException(
          httpStatus: 404,
          message: '资产 $id 不存在或不属于当前用户',
        );
      }
      return <String, dynamic>{'ok': true};
    }

    throw _notImplemented('DELETE', path);
  }

  @override
  Future<Map<String, dynamic>> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    String? mimeType,
  }) async {
    _advance();
    final userId = _requireUserId();

    if (path != ApiPaths.uploadImage) {
      throw _notImplemented('POST(upload)', path);
    }

    // §9.4：对齐 provider 的限制，超大图直接挡在门外，
    // 不要等传完了才被 provider 拒绝（那已经花了带宽）
    if (bytes.length > _maxImageBytes) {
      throw AppException.fromResponse(
        httpStatus: ApiErrorCode.imageTooLarge.httpStatus,
        codeWire: ApiErrorCode.imageTooLarge.wire,
      );
    }

    final id = _nextId++;
    final url = 'https://mock-oss.local/u/$userId/$id/$filename';
    _assets.add(<String, dynamic>{
      'id': id,
      'user_id': userId,
      'task_id': null,
      'kind': 'image',
      'public_url': url,
      'mime': mimeType ?? 'image/png',
      'size_bytes': bytes.length,
      'created_at': _clock().toUtc().toIso8601String(),
      // 用户自己上传的原图**不是** AI 生成的，不该打 AI 标识。
      // 这就是 Asset.isAiGenerated 为什么不能写死成 true 的原因（见 asset.dart）。
      'is_ai_generated': false,
    });

    // 【⚠️ 这里同时返回 asset_id 和 public_url，是刻意的】
    // §12.1 的表格里，`/uploads/image` 只写了「返回公网 URL」，
    // 但 `/generation/video` 要的参数却是 `source_asset_id` —— 文档自相矛盾：
    // 一个说给 URL，一个说要 id。
    // 两个都给，App 就能用 id 提交、用 URL 显示预览。**需与后端确认取哪个。**
    return <String, dynamic>{'asset_id': id, 'public_url': url};
  }

  // ═══════════════════════════════════════════════════════════
  //  认证 §6.1 / §12.1
  // ═══════════════════════════════════════════════════════════

  Map<String, dynamic> _register(Map<String, dynamic> body) {
    final username = _requiredString(body, 'username');
    final password = _requiredString(body, 'password');
    final inviteCode = _requiredString(body, 'invite_code');

    // §6.1：注册需要邀请码（内测控量，邀请制本身就是花销上限）。
    // Mock 不做邀请码白名单校验，**任何非空邀请码都通过** ——
    // 验收剧本里用 MOCK 即可。真后端会去 invite_codes 表里查。
    if (inviteCode.isEmpty) {
      throw AppException(httpStatus: 400, message: '邀请码不能为空');
    }

    if (_usersByUsername.containsKey(username)) {
      // 【⚠️ 契约缺口】§12.3 没有「用户名已存在」这个错误码。
      // 真后端需要补一个（比如 409 USERNAME_TAKEN），否则客户端只能靠文案判断。
      throw AppException(httpStatus: 409, message: '用户名「$username」已被占用');
    }

    final id = _nextId++;
    final user = _FakeUser(
      id: id,
      username: username,
      password: password,
      createdAt: _clock().toUtc(),
    );
    _usersByUsername[username] = user;
    _usersById['$id'] = user;
    _accounts['$id'] = _FakeAccount();

    // §12.1：新用户赠 50 积分。**必须写流水**（§7.3：每一笔都要写流水），
    // 否则用户会看到余额 50 但流水是空的，第一反应是「这钱哪来的」。
    _grant(userId: '$id', amount: _signupGrant, note: '新用户注册赠送');

    final token = _issueToken(user);
    return _sessionResponse(token: token, userId: '$id');
  }

  Map<String, dynamic> _login(Map<String, dynamic> body) {
    final username = _requiredString(body, 'username');
    final password = _requiredString(body, 'password');

    final user = _usersByUsername[username];
    // 【安全纪律】用户名不存在和密码错误返回**同一句**话。
    // 分开写等于给攻击者一个「这个用户名存不存在」的探测器。
    if (user == null || user.password != password) {
      throw AppException(httpStatus: 401, message: '用户名或密码不正确');
    }

    final token = _issueToken(user);
    return _sessionResponse(token: token, userId: '${user.id}');
  }

  String _issueToken(_FakeUser user) {
    final token = 'mock-token-${user.id}-${_nextId++}';
    _userIdByToken[token] = '${user.id}';
    _currentToken = token;
    return token;
  }

  /// 登录/注册的统一返回。
  ///
  /// 【这一条超出了 §12.1 的字面】文档只写 `→ {token}`。
  /// 这里额外带回 user 和 credit_account，理由是：**登录后马上要进首页，
  /// 而首页右上角就有积分胶囊**。只给 token 的话必须再补一个 `/me`，
  /// 用户会看到「进去了 → 积分那栏空一下 → 数字才出来」的闪烁。
  /// 见 `lib/models/auth_session.dart` 的同类说明。
  Map<String, dynamic> _sessionResponse({
    required String token,
    required String userId,
  }) =>
      <String, dynamic>{
        'token': token,
        'user': _usersById[userId]!.toJson(),
        'credit_account': _accountOf(userId).toJson(_clock().toUtc()),
      };

  // ═══════════════════════════════════════════════════════════
  //  用户与积分 §12.1
  // ═══════════════════════════════════════════════════════════

  Map<String, dynamic> _me() {
    final userId = _requireUserId();
    return <String, dynamic>{
      'user': _usersById[userId]!.toJson(),
      'credit_account': _accountOf(userId).toJson(_clock().toUtc()),
    };
  }

  Map<String, dynamic> _ledgerPage(Map<String, dynamic>? query) {
    final userId = _requireUserId();
    final mine = _ledger.where((e) => e['user_id'] == userId).toList()
      // 最新的在最前面 —— 用户点进流水第一个想看的是刚才那笔
      //
      // ─────────────────────────────────────────────────────
      // 【为什么必须解析成 DateTime 再比，不能直接比 created_at 字符串】
      //
      // 因为 `DateTime.toIso8601String()` 的**长度不固定**：
      // 微秒为 0 时输出 `...:00.123Z`（3 位小数），不为 0 时是
      // `...:00.123456Z`（6 位）。按字符串逐字符比时，
      // `Z`(0x5A) 比 `4`(0x34) 大 —— 于是「同一毫秒里的两条记录」
      // 顺序会**颠倒**，用户会看到早的一条排在新的一条前面。
      //
      // 这不是理论问题：24 条连写的流水分页回来是
      // `23, 22, 2, 3, …, 19 | 20, 21, 0, 1`。真后端不会踩这个坑
      // （SQL 按时间列排），这个坑是 Mock 自己造的，也得自己拆掉。
      //
      // 【为什么拿 id 兜底】同一微秒写进来的多条（注册赠送 + 人工调整）
      // 时间可能完全相同，只按时间排的话先后由排序算法决定，不稳定。
      // id 是单调递增的，正好当「写入顺序」用。
      // ─────────────────────────────────────────────────────
      ..sort((a, b) {
        final byTime = DateTime.parse(b['created_at'] as String)
            .compareTo(DateTime.parse(a['created_at'] as String));
        return byTime != 0 ? byTime : (b['id'] as int).compareTo(a['id'] as int);
      });

    final page = _intQuery(query, 'page', 1);
    final pageSize = _intQuery(query, 'page_size', 20);
    final start = (page - 1) * pageSize;
    final slice = start >= mine.length
        ? <Map<String, dynamic>>[]
        : mine.sublist(start, (start + pageSize).clamp(0, mine.length));

    return <String, dynamic>{
      'items': slice,
      'page': page,
      'page_size': pageSize,
      'total': mine.length,
    };
  }

  // ═══════════════════════════════════════════════════════════
  //  问价 §12.1 / §7.2
  // ═══════════════════════════════════════════════════════════

  /// `GET /generation/cost?kind=&duration=&ratio=`
  ///
  /// 【⚠️ 查询参数是本项目在 B2 拍板冻结的】§12.1 只写了返回 `{min,max,freeze}`，
  /// 没说传什么。详见 `api_paths.dart` 里 `generationCost` 的注释。
  Map<String, dynamic> _costEstimate(Map<String, dynamic>? query) {
    _requireUserId();

    final kind = TaskKind.fromWire(
      (query?['kind'] as String?) ?? TaskKind.textToImage.wire,
    );
    final duration = _intQuery(query, 'duration', 5);

    if (kind == TaskKind.textToImage) {
      // 图片成本固定（§7.2：freeze = 4，等于结算额），所以区间上下限相同。
      // credit_format.isFixed 会把这种情形显示成「本次冻结 4 积分」而不是「4~4 积分」。
      return <String, dynamic>{
        'min': _creditsPerImage,
        'max': _creditsPerImage,
        'freeze': _creditsPerImage,
      };
    }

    // 视频：下限按用户选的时长，上限按预留了余量的时长（§7.2 的「请求时长上限」）。
    // 【为什么要给区间而不是一个数】因为成片时长由 provider 侧的 Agent 决定，
    // 下单时连后端都不知道最终会扣多少 —— 这就是 §13.4 禁止在按钮下写确定数字的原因。
    final min = _creditsPerSecond720 * duration;
    final max = _creditsPerSecond720 * (duration + _durationSlackSec);
    return <String, dynamic>{'min': min, 'max': max, 'freeze': max};
  }

  // ═══════════════════════════════════════════════════════════
  //  提交生成 §7.2 / §7.5
  // ═══════════════════════════════════════════════════════════

  Map<String, dynamic> _submitImage(Map<String, dynamic> body) {
    final prompt = _requiredString(body, 'prompt');
    return _submit(
      kind: TaskKind.textToImage,
      prompt: prompt,
      // 注意这里读的是 `aspect_ratio`：§12.1 里图片接口用 aspect_ratio，
      // 视频接口却用 ratio —— 文档自己不一致。对外照抄契约，
      // 对内统一存成 TaskParams.ratio（所以下面传进去时就归一了）。
      params: TaskParams(
        ratio: body['aspect_ratio'] as String?,
      ),
      sourceAssetId: null,
      durationSec: 0,
      idempotencyKey: _requiredString(body, 'idempotency_key'),
    );
  }

  Map<String, dynamic> _submitVideo(Map<String, dynamic> body) {
    final prompt = _requiredString(body, 'prompt');
    final duration = body['duration'] is num
        ? (body['duration'] as num).toInt()
        : 5;
    return _submit(
      kind: TaskKind.imageToVideo,
      prompt: prompt,
      params: TaskParams(
        ratio: body['ratio'] as String?,
        duration: duration,
      ),
      sourceAssetId: body['source_asset_id'] as String?,
      durationSec: duration,
      idempotencyKey: _requiredString(body, 'idempotency_key'),
    );
  }

  /// 提交的统一入口 —— §7.5 四道闸里有三道在这一段里。
  Map<String, dynamic> _submit({
    required TaskKind kind,
    required String prompt,
    required TaskParams params,
    required String? sourceAssetId,
    required int durationSec,
    required String idempotencyKey,
  }) {
    final userId = _requireUserId();

    // ── 校验：提示词（§11.2 ≤2000 字，提交前校验）──────────
    if (prompt.trim().isEmpty || prompt.length > _maxPromptLength) {
      throw AppException.fromResponse(
        httpStatus: ApiErrorCode.invalidPrompt.httpStatus,
        codeWire: ApiErrorCode.invalidPrompt.wire,
      );
    }

    // ── 校验：图生视频必须有参考图 ────────────────────────
    // 拦在这里比让 provider 报一个看不懂的错要好得多
    if (kind.needsSourceImage && (sourceAssetId == null || sourceAssetId.isEmpty)) {
      throw AppException(
        httpStatus: 400,
        message: '${kind.label}任务必须提供参考图（source_asset_id）',
      );
    }

    // ── 第 2 道闸：幂等键去重（§7.5）───────────────────────
    //
    // 【这道闸为什么必须在冻结之前】因为它的作用就是**防连点双扣**。
    // 用户双击生成按钮 → 两个请求带着同一个 key 到达 →
    // 如果先冻结再查重，钱已经被扣两次了，再发现重复也没用。
    final existingId = _taskIdByIdempotencyKey[idempotencyKey];
    if (existingId != null) {
      final existing = _tasks.firstWhere((t) => t.id == existingId);
      // §12.3：`DUPLICATE_REQUEST` 的客户端行为是**静默复用已存在的任务**。
      // 所以这里除了错误码，还把任务本体一起放回响应里 ——
      // 否则客户端拿到一个 409 却不知道是哪个任务，还得再查一次。
      throw AppException.fromResponse(
        httpStatus: ApiErrorCode.duplicateRequest.httpStatus,
        codeWire: ApiErrorCode.duplicateRequest.wire,
        message: '幂等键重复，复用任务 $existingId',
        body: <String, dynamic>{'task': existing.toJson(queuePosition: 0)},
      );
    }

    // ── 第 3 道闸：配额（§7.5 / §8.2）──────────────────────
    _checkQuota(userId: userId, kind: kind);

    // ── 第 1 道闸：先冻结后提交（§7.5）──────────────────────
    final freeze = kind == TaskKind.textToImage
        ? _creditsPerImage
        : _creditsPerSecond720 * (durationSec + _durationSlackSec);

    final id = _nextId++;
    final account = _accountOf(userId);

    // 可用余额 = balance − frozen，**现算**（§7.3）
    if (account.balance - account.frozen < freeze) {
      throw AppException.fromResponse(
        httpStatus: ApiErrorCode.insufficientCredits.httpStatus,
        codeWire: ApiErrorCode.insufficientCredits.wire,
      );
    }

    account.frozen += freeze;
    _writeLedger(
      userId: userId,
      kind: 'freeze',
      amount: freeze,
      taskId: id,
      note: '提交任务预扣',
    );

    final task = _FakeTask(
      id: id,
      userId: userId,
      kind: kind,
      prompt: prompt,
      params: params,
      sourceAssetId: sourceAssetId,
      idempotencyKey: idempotencyKey,
      freezeAmount: freeze,
      inputDurationSec: 0,
      creditsPerSecond: _creditsPerSecond720,
      requestedDurationSec: durationSec,
      createdAt: _clock().toUtc(),
    );
    _tasks.add(task);
    // 【这一行就是第 2 道闸的本体】把幂等键登记下来，下次同 key 进来就会被拦。
    // 漏了这一行，去重逻辑写得再漂亮也一次都不会触发 —— 而后果是
    // 用户双击一次生成按钮就被扣两次钱。
    _taskIdByIdempotencyKey[idempotencyKey] = id;

    if (latency == null) {
      // 极简模式：立刻走完全程。**依然要真的结算**（见类注释里的第 2 条）。
      _complete(task);
    } else {
      task.transitionTo(TaskStatus.queued, _clock().toUtc());
    }

    return task.toJson(queuePosition: 0);
  }

  /// 第 3 道闸：配额。
  ///
  /// 【为什么每日上限这一条，即使开着极简模式也必须真做】
  /// 因为它是**唯一一条不用开 latency 开关就能触发的闸门** ——
  /// 连点 21 次就能命中。如果 Mock 不抛 `RATE_LIMITED`，
  /// UI 里「已达今日生成上限」那个分支将**永远没有被执行过**，
  /// 上线当天才发现它写错了。
  void _checkQuota({required String userId, required TaskKind kind}) {
    final now = _clock().toUtc();
    final today = DateTime.utc(now.year, now.month, now.day);

    final todaysTasks = _tasks.where(
      (t) =>
          t.userId == userId &&
          !t.createdAt.isBefore(today) &&
          t.createdAt.isBefore(today.add(const Duration(days: 1))),
    ).length;

    if (todaysTasks >= _dailyTaskLimit) {
      throw AppException.fromResponse(
        httpStatus: ApiErrorCode.rateLimited.httpStatus,
        codeWire: ApiErrorCode.rateLimited.wire,
        message: '已达每日上限 $_dailyTaskLimit 个',
      );
    }

    // §8.2：图与视频**分开计数**。混在一起的话图片会被视频饿死 ——
    // 用户排了一个十分钟的视频之后，连张图都生成不了。
    final activeOfKind =
        _tasks.where((t) => t.userId == userId && t.kind == kind && t.status.isActive).length;

    if (activeOfKind >= _maxConcurrentPerKind) {
      throw AppException.fromResponse(
        httpStatus: ApiErrorCode.rateLimited.httpStatus,
        codeWire: ApiErrorCode.rateLimited.wire,
        message: '同时进行的${kind.label}任务不能超过 $_maxConcurrentPerKind 个',
      );
    }
  }

  // ═══════════════════════════════════════════════════════════
  //  状态机推进 §8.3
  // ═══════════════════════════════════════════════════════════

  /// 按流逝的时间推进所有未完成的任务。
  ///
  /// 【为什么「读的时候才推进」是对的】
  /// 真实后端的推进发生在 worker 进程里，与客户端无关。
  /// Mock 没有后台线程，只能借用「客户端来读了」这个时机往前推。
  /// 效果上**客户端观察到的东西是一样的** ——
  /// 因为它本来就只能通过轮询看到变化。
  ///
  /// 【latency 为 null 时它什么都不做】极简模式下任务在提交那一刻就已经完成了。
  void _advance() {
    final stage = latency;
    if (stage == null) return;

    final now = _clock().toUtc();
    for (final task in _tasks) {
      if (task.status.isTerminal) continue;

      final elapsed = now.difference(task.createdAt);
      if (elapsed >= stage * 2) {
        // 该完成了。先补上 submitted 的时间戳，再收尾 ——
        // 否则详情页会出现「succeeded 但从来没有 submitted_at」这种自相矛盾的记录。
        task.transitionTo(TaskStatus.submitted, task.createdAt.add(stage));
        _complete(task);
      } else if (elapsed >= stage) {
        task.transitionTo(TaskStatus.submitted, task.createdAt.add(stage));
      } else {
        task.transitionTo(TaskStatus.queued, task.createdAt);
      }
    }
  }

  /// 收尾：结算 + 退回 + 落资产。这是 §7.2 的三段式的后两段。
  void _complete(_FakeTask task) {
    if (task.status.isTerminal) return;

    final account = _accountOf(task.userId);

    // ── 结算：按**实际**成片时长算 ──────────────────────────
    //
    // 【Mock 的成片时长怎么来的】真实情况下由 provider 回参的 `Duration` 决定
    // （见 §11.2 的 output_duration_sec）。Mock 用「请求时长 + 1 秒」来模拟
    // Agent 的自主偏移 —— 这个偏差正是「下单时算不出准确价格」的根源，
    // 所以 Mock 必须把它演出来，否则「退回差额」这条路径永远是零。
    final outputDuration = task.requestedDurationSec == 0
        // 文生图没有时长概念，成本固定 4 积分
        ? 0
        : task.requestedDurationSec + 1;
    task.outputDurationSec = outputDuration;

    final rawSettle = task.kind == TaskKind.textToImage
        ? _creditsPerImage
        : task.creditsPerSecond * (task.inputDurationSec + outputDuration);

    // §7.2 ④：实际 > 冻结上限时，**平台自担差额**。
    // 也就是说用户最多被扣到冻结额为止，超出部分平台认。
    // 不设这个上限的话，账户余额会被扣成负数。
    final settle = rawSettle > task.freezeAmount ? task.freezeAmount : rawSettle;

    // ── 落账：settle 与 refund 必须在同一个事务里（§7.3）────
    //
    // 【为什么这一步不能拆开】拆开就可能出现「扣了钱但没记流水」
    // 或「任务成功了但冻结没释放」—— 两种都是对不上账的事故。
    // 这里没有真事务，就把这几行写在一起，让它们的原子性一眼可见。
    account.balance -= settle;
    account.frozen -= task.freezeAmount;

    _writeLedger(
      userId: task.userId,
      kind: 'settle',
      amount: settle,
      taskId: task.id,
      note: '按成片时长结算',
    );

    final refund = task.freezeAmount - settle;
    if (refund > 0) {
      _writeLedger(
        userId: task.userId,
        kind: 'refund',
        amount: refund,
        taskId: task.id,
        note: '退回多冻结的积分',
      );
    }

    task.settledAmount = settle;
    task.outputDurationSec = outputDuration;
    task.transitionTo(TaskStatus.succeeded, _clock().toUtc());

    _createAssetsFor(task);
  }

  /// 任务成功后把产物落成资产（§11.2 的 assets 表）。
  ///
  /// 【为什么视频要连封面一起落】因为作品列表一屏要摆九个视频。
  /// 每个都直接加载视频文件当封面的话，流量和内存都会炸。
  /// 封面是单独一张小图，列表读它，点开才读视频。
  void _createAssetsFor(_FakeTask task) {
    final now = _clock().toUtc().toIso8601String();
    final isVideo = task.kind != TaskKind.textToImage;

    _assets.add(<String, dynamic>{
      'id': _nextId++,
      'user_id': task.userId,
      'task_id': task.id,
      'kind': isVideo ? 'video' : 'image',
      'public_url': isVideo
          ? 'https://mock-oss.local/t/${task.id}/out.mp4'
          : 'https://mock-oss.local/t/${task.id}/out.png',
      'mime': isVideo ? 'video/mp4' : 'image/png',
      'duration_sec': isVideo ? task.outputDurationSec : null,
      'width': isVideo ? 1280 : 1024,
      'height': isVideo ? 720 : 1024,
      // 平台产物一律是 AI 生成（§11.2 恒为 true），合规标识要靠它
      'is_ai_generated': true,
      'created_at': now,
    });

    if (isVideo) {
      _assets.add(<String, dynamic>{
        'id': _nextId++,
        'user_id': task.userId,
        'task_id': task.id,
        'kind': 'thumbnail',
        'public_url': 'https://mock-oss.local/t/${task.id}/thumb.jpg',
        'mime': 'image/jpeg',
        'width': 1280,
        'height': 720,
        'is_ai_generated': true,
        'created_at': now,
      });
    }
  }

  // ═══════════════════════════════════════════════════════════
  //  任务列表 / 详情 / 取消
  // ═══════════════════════════════════════════════════════════

  Map<String, dynamic> _taskList(Map<String, dynamic>? query) {
    final userId = _requireUserId();
    final filter = query?['status'] as String?;

    var mine = _tasks.where((t) => t.userId == userId).toList();

    if (filter == ApiPaths.statusActive) {
      mine = mine.where((t) => t.status.isActive).toList();
    } else if (filter == ApiPaths.statusDone) {
      mine = mine.where((t) => t.status.isTerminal).toList();
    }

    // 新的排在前面
    mine.sort((a, b) => b.createdAt.compareTo(a.createdAt));

    final items = <Map<String, dynamic>>[];
    for (final t in mine) {
      items.add(t.toJson(queuePosition: _queuePositionOf(t)));
    }

    return <String, dynamic>{
      'items': items,
      'page': 1,
      'page_size': items.length,
      'total': items.length,
    };
  }

  _FakeTask _taskDetail(String rawId) {
    final userId = _requireUserId();
    final id = _parseId(rawId, what: '任务');
    for (final t in _tasks) {
      if (t.id == id && t.userId == userId) return t;
    }
    throw AppException(httpStatus: 404, message: '任务 $id 不存在');
  }

  /// 排队位次（§8.2：诚实显示位次，不做假进度条）。
  ///
  /// 【返回 null 而不是 0 的情形很重要】只有 queued 才有「前面还有几个」可言。
  /// 已经 submitted 的任务前面没有任何人 —— 但那时显示「前面还有 0 个」是错的，
  /// 因为用户会以为马上出结果，其实还要等好几分钟。所以那种情况返回 null，
  /// 让 UI 干脆不显示这一行。
  int? _queuePositionOf(_FakeTask task) {
    if (task.status != TaskStatus.queued) return null;
    var ahead = 0;
    for (final t in _tasks) {
      // §8.2：图与视频分开计数，所以位次也只在同类里数
      if (t.kind == task.kind && t.status == TaskStatus.queued && t.createdAt.isBefore(task.createdAt)) {
        ahead++;
      }
    }
    return ahead + 1;
  }

  /// `POST /tasks/{id}/cancel`
  Map<String, dynamic> _cancelTask(String rawId) {
    final task = _taskDetail(rawId);

    if (task.status.isTerminal) {
      throw AppException(
        httpStatus: 409,
        message: '任务已经是${task.status.label}，不能再取消',
      );
    }

    final account = _accountOf(task.userId);

    // §7.4 退费政策：**只有排队中取消才全额退回**。
    // 已提交给 provider 之后取消是**不退**的 —— provider 已经在跑，钱已经花出去了。
    // 这个区别必须在 Mock 里如实体现，不能一律全退：
    // 否则 UI 上「取消会退多少」的提示永远是错的，用户会在真的被扣钱时投诉。
    final refundable = task.status == TaskStatus.pending ||
        task.status == TaskStatus.queued;

    account.frozen -= task.freezeAmount;

    if (refundable) {
      _writeLedger(
        userId: task.userId,
        kind: 'refund',
        amount: task.freezeAmount,
        taskId: task.id,
        note: '排队中取消，全额退回',
      );
      task.settledAmount = 0;
    } else {
      // 已提交：钱已经花给 provider 了，照冻结额实扣
      account.balance -= task.freezeAmount;
      _writeLedger(
        userId: task.userId,
        kind: 'settle',
        amount: task.freezeAmount,
        taskId: task.id,
        note: '已提交给生成服务后取消，不予退回',
      );
      task.settledAmount = task.freezeAmount;
    }

    task.transitionTo(TaskStatus.canceled, _clock().toUtc());
    return task.toJson(queuePosition: null);
  }

  // ═══════════════════════════════════════════════════════════
  //  资产 §12.1
  // ═══════════════════════════════════════════════════════════

  Map<String, dynamic> _assetPage(Map<String, dynamic>? query) {
    final userId = _requireUserId();
    var mine = _assets.where((a) => a['user_id'] == userId).toList();

    // `?task_id=` —— 本项目拍板冻结的契约补充（§12.1 只写了分页参数）。
    // 理由见 `AssetRepository.fetchAssets` 的注释：结果页要问「这个任务产出了什么」，
    // 而产物在 assets 表里是独立一行，只能靠 task_id 关联。
    // 【为什么在服务端筛而不是客户端筛】作品会越攒越多，
    // 为了看一个结果把 200 条记录拉下来是不合理的。
    final taskId = _intQueryOrNull(query, 'task_id');
    if (taskId != null) {
      mine = mine.where((a) => a['task_id'] == taskId).toList();
    }
    if (query?['certified_only'] == true) mine = [];

    final page = _intQuery(query, 'page', 1);
    final pageSize = _intQuery(query, 'page_size', 20);
    final start = (page - 1) * pageSize;
    final slice = start >= mine.length
        ? <Map<String, dynamic>>[]
        : mine.sublist(start, (start + pageSize).clamp(0, mine.length));

    return <String, dynamic>{
      'items': slice,
      'page': page,
      'page_size': pageSize,
      'total': mine.length,
    };
  }

  // ═══════════════════════════════════════════════════════════
  //  账本（§7.3：每一笔都要写流水）
  // ═══════════════════════════════════════════════════════════

  void _grant({
    required String userId,
    required int amount,
    required String note,
  }) {
    _accountOf(userId).balance += amount;
    _writeLedger(userId: userId, kind: 'grant', amount: amount, note: note);
  }

  /// 【仅供演示与测试】模拟管理员发放积分 —— §15.1 验收剧本的第 2 步。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【为什么必须有这个后门，而不是让 App 有个充值按钮】
  ///
  /// §15.1 的剧本原话是「新用户凭邀请码注册 → **管理员脚本发 50 积分** → 登录」。
  /// 那个脚本是**服务端的东西**（见 §16 人工步骤总表），不是 App 的接口。
  /// v1 **不接支付**（§7.6），所以 App 侧一个充值入口都不该有 ——
  /// 谁要是往积分页加了「充值」按钮，那是把 v3 的功能提前做了。
  ///
  /// 但要让验收剧本能跑，Mock 就得能表演「管理员发了一笔」。
  /// 所以留这个 debug 后门，它写一条 `adjust` 流水（§7.3 的第五种 kind），
  /// 和真脚本干的事一模一样。
  ///
  /// 【为什么名字里一定要带 debug】
  /// 页面代码里出现 `debugXxx` 会让人停下来问一句「这是干嘛的」，
  /// 而叫 `grantCredits` 就会被当成一个正常业务方法调用 —— 那等于
  /// 在客户端给自己发钱。
  /// ─────────────────────────────────────────────────────────
  void debugGrantCredits(int amount, {String note = '管理员发放（演示用）'}) {
    final userId = _requireUserId();
    _accountOf(userId).balance += amount;
    _writeLedger(userId: userId, kind: 'adjust', amount: amount, note: note);
  }

  /// 写一条流水。
  ///
  /// 【为什么要强制带上 balance_after / frozen_after】
  /// §7.3 明确要求「`balance_after` 落库，便于对账」。
  /// 这不是冗余：用户来问「我这 5 积分去哪了」的时候，
  /// 只有这一列能证明每一步之后账户到底是什么状态。
  /// 靠 amount 累加去还原是**不可靠的** —— 只要有一笔金额记错方向，整条链就全错。
  void _writeLedger({
    required String userId,
    required String kind,
    required int amount,
    required String note,
    int? taskId,
  }) {
    final account = _accountOf(userId);
    _ledger.add(<String, dynamic>{
      'id': _nextId++,
      'user_id': userId,
      'kind': kind,
      // amount 恒为正数，方向看 kind（见 credit_ledger_entry.dart 的说明）
      'amount': amount,
      'balance_after': account.balance,
      'frozen_after': account.frozen,
      'task_id': taskId,
      'note': note,
      'created_at': _clock().toUtc().toIso8601String(),
    });
  }

  _FakeAccount _accountOf(String userId) =>
      _accounts.putIfAbsent(userId, _FakeAccount.new);

  // ═══════════════════════════════════════════════════════════
  //  小工具
  // ═══════════════════════════════════════════════════════════

  /// 取当前登录用户 id，没登录就抛 401。
  ///
  /// 【为什么 401 要由通信层统一抛】因为它是**跨所有接口**的横切规则。
  /// 让每个 repository 自己判断的话，只要有一处漏了，
  /// 就会出现「token 早失效了，页面还在一直重试、一直转圈」。
  String _requireUserId() {
    final token = _currentToken;
    final userId = token == null ? null : _userIdByToken[token];
    if (userId == null) throw AppException.unauthorized();
    return userId;
  }

  Map<String, dynamic> _body(Object? body) =>
      body == null ? <String, dynamic>{} : _asMap(body);

  Map<String, dynamic> _asMap(Object value) => value is Map<String, dynamic>
      ? value
      : (value as Map).map((k, v) => MapEntry(k.toString(), v));

  /// 取必填字符串参数。缺了就是**调用方写错了**，不是业务错误。
  ///
  /// 【为什么这里抛的是普通异常而不是 AppException】
  /// 因为「缺少 idempotency_key」说明前端代码有 bug，不是用户能处理的情况。
  /// 把它包装成一个 `AppException` 会让它看起来像业务失败，
  /// 于是被当成「服务端拒绝」记录下来，真正的原因反而被埋掉。
  String _requiredString(Map<String, dynamic> body, String key) {
    final value = body[key];
    if (value is String) return value;
    if (value == null) {
      throw ArgumentError('缺少必填参数「$key」。这是调用方的 bug，不是业务错误。');
    }
    throw ArgumentError('参数「$key」应该是字符串，实际是 ${value.runtimeType}');
  }

  int _intQuery(Map<String, dynamic>? query, String key, int fallback) {
    final value = query?[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) return int.tryParse(value) ?? fallback;
    return fallback;
  }

  /// 「没传这个参数」和「传了一个空值」是两回事，所以这里返回可空。
  ///
  /// 【为什么不能拿 [_intQuery] 的 fallback 凑合】因为「没筛」和「筛 0」
  /// 会给出完全不同的结果。给 0 当默认值的话，不带参数的请求会筛出空列表。
  int? _intQueryOrNull(Map<String, dynamic>? query, String key) {
    final value = query?[key];
    if (value == null) return null;
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) return int.tryParse(value);
    return null;
  }

  int _parseId(String raw, {required String what}) {
    final id = int.tryParse(raw);
    if (id == null) {
      throw AppException(httpStatus: 400, message: '$what id「$raw」不是数字');
    }
    return id;
  }

  List<String> _segments(String path) =>
      path.split('/').where((s) => s.isNotEmpty).toList();

  AppException _notImplemented(String method, String path) => AppException(
        message: 'Mock 未实现：$method $path',
      );
}

// ═══════════════════════════════════════════════════════════════════
//  内部记录类型（只在本文件用，所以是私有的）
// ═══════════════════════════════════════════════════════════════════

class _FakeUser {
  _FakeUser({
    required this.id,
    required this.username,
    required this.password,
    required this.createdAt,
  });

  final int id;
  final String username;
  final String password;
  final DateTime createdAt;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'username': username,
        'created_at': createdAt.toIso8601String(),
        // 【注意这里没有 password】模拟服务端也**绝不**把密码放回响应里。
        // §6.1 要求密码必须哈希存储；这里连返回都不返回。
      };
}

class _FakeAccount {
  int balance = 0;
  int frozen = 0;

  Map<String, dynamic> toJson(DateTime updatedAt) => <String, dynamic>{
        'balance': balance,
        'frozen': frozen,
        // 【注意没有 available 字段】§7.3 明令「可用余额永远现算，不单独存字段」。
        // 服务端不返回它，客户端用 `balance − frozen` 自己算
        // （见 CreditAccount.available）。两边都不存，就不会不一致。
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}

class _FakeTask {
  _FakeTask({
    required this.id,
    required this.userId,
    required this.kind,
    required this.prompt,
    required this.params,
    required this.sourceAssetId,
    required this.idempotencyKey,
    required this.freezeAmount,
    required this.inputDurationSec,
    required this.creditsPerSecond,
    required this.requestedDurationSec,
    required this.createdAt,
  });

  final int id;
  final String userId;
  final TaskKind kind;
  final String prompt;
  final TaskParams params;
  final String? sourceAssetId;
  final String idempotencyKey;
  final int freezeAmount;
  final int inputDurationSec;
  final int creditsPerSecond;
  final int requestedDurationSec;
  final DateTime createdAt;

  TaskStatus status = TaskStatus.pending;
  int? settledAmount;
  int? outputDurationSec;
  DateTime? queuedAt;
  DateTime? submittedAt;
  DateTime? finishedAt;

  /// 状态流转，顺带记下时间戳。
  void transitionTo(TaskStatus next, DateTime at) {
    status = next;
    switch (next) {
      case TaskStatus.queued:
        queuedAt ??= at;
      case TaskStatus.submitted:
        submittedAt ??= at;
      case TaskStatus.succeeded:
      case TaskStatus.failed:
      case TaskStatus.rejected:
      case TaskStatus.canceled:
      case TaskStatus.expired:
        finishedAt ??= at;
      case TaskStatus.pending:
        break;
    }
  }

  Map<String, dynamic> toJson({required int? queuePosition}) => <String, dynamic>{
        'id': id,
        'kind': kind.wire,
        'status': status.wire,
        'prompt': prompt,
        'params': params.toJson(),
        'source_asset_id': sourceAssetId,
        'idempotency_key': idempotencyKey,
        'freeze_amount': freezeAmount,
        'settled_amount': settledAmount,
        'input_duration_sec': inputDurationSec,
        'output_duration_sec': outputDurationSec,
        'queue_position': queuePosition,
        // 【这里没有 provider_url】§11.2 的表里确实有这一列，但它是
        // 「瞬时中转用，不作为资产真身」（文档原话）——
        // 即梦给的 URL 只活 1 小时，App 永远不该碰。
        // 所以 Mock 也**不返回它**，从源头上断掉误用。
        'created_at': createdAt.toIso8601String(),
        'queued_at': queuedAt?.toIso8601String(),
        'submitted_at': submittedAt?.toIso8601String(),
        'finished_at': finishedAt?.toIso8601String(),
      };
}
