import '../core/json_utils.dart';

class VideoEvidence {
  const VideoEvidence({
    required this.status,
    this.evidenceId,
    this.sha256,
    this.txId,
    this.channel,
    this.networkId,
    this.recordedAt,
  });

  final String status;
  final String? evidenceId;
  final String? sha256;
  final String? txId;
  final String? channel;
  final String? networkId;
  final DateTime? recordedAt;

  bool get isWaiting => status == 'pending' || status == 'submitted';

  factory VideoEvidence.fromJson(Map<String, dynamic> json) => VideoEvidence(
    status: json.stringOr(json['status'], 'not_recorded'),
    evidenceId: json.asStringOrNull(json['evidence_id']),
    sha256: json.asStringOrNull(json['sha256']),
    txId: json.asStringOrNull(json['tx_id']),
    channel: json.asStringOrNull(json['channel']),
    networkId: json.asStringOrNull(json['network_id']),
    recordedAt: json.asDateTimeOrNull(json['recorded_at']),
  );
}
