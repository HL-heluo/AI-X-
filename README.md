# AIVideo · AI 视频创作平台

Flutter 客户端与 FastAPI 后端提供图片生成、图生视频、积分账本和作品管理。双链演示使用 Ganache 同步 VCR 测试积分，使用 Hyperledger Fabric 保存视频存证与作品转让回执。网页支持访客公开核验和站内作品交易。

| 目录 | 内容 |
| --- | --- |
| [flutter_application_1](flutter_application_1/) | Flutter 前端与界面回归测试 |
| [backend](backend/) | FastAPI、数据库迁移与 API 测试 |
| [双链存证](双链存证/) | Ganache 合约、Fabric 链码与网关 |
| [上线本地](上线本地/) | Windows 演示环境启动脚本和验收脚本 |

本地演示的启动顺序、配置和验收方法见[双链启动手册](上线本地/双链启动.md)。使用你自己的测试服务器地址，并按实际目录调整示例路径。后端配置项见[环境变量示例](backend/.env.example)。
