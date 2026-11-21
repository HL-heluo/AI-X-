# Fabric 环境搭建（Windows + WSL2 + Docker）

> 第 0 至 3 节用于准备环境。当前平台链码部署、签发登记身份和启动网关按 [本地双链启动](../../上线本地/双链启动.md) 执行。

> 目标：在 WSL2 里的 Ubuntu 跑起 fabric-samples 的 test-network（Org1 + Org2 两个组织），
> 在 `videochannel` 通道上以 `AND('Org1MSP.peer','Org2MSP.peer')` 策略部署 `video-evidence` 链码，
> 并让 Windows 侧的 Python 通过 bridge 调用它。
>
> 这条路走通的标志：`peer chaincode query` 能读回你自己写进去的存证记录。
> 预计耗时：顺利 3~4 小时，网络慢/踩坑 1~2 天。

---

## 0. 前置检查

在 **管理员 PowerShell** 里：

```powershell
wsl --status        # 没输出/报错 = 没装好
wsl -l -v           # 应看到 Ubuntu 且 VERSION = 2
docker --version    # Windows 侧不需要 Docker Desktop
```

在 **WSL** 里（`wsl` 进入）：

```bash
docker --version
docker run --rm hello-world
free -h             # 建议 ≥ 8G；Docker + 3 个 peer + orderer 吃内存
df -h               # 建议 ≥ 20G 空闲
```

---

## 1. 安装 WSL2 + Ubuntu（已装可跳过）

```powershell
wsl --install -d Ubuntu-24.04
# 装完重启；首次进入设置 Linux 用户名/密码
```

如果 `wsl --install` 报「已安装但无发行版」：

```powershell
wsl --update
wsl --set-default-version 2
```

> 不要为了省事装 Docker Desktop：它和 WSL 的集成偶尔会在 peer 端口（7051/9051）上打架，
> 而且多一层网络转发。WSL 里直接装 docker.io 最稳。

---

## 2. 在 WSL 里装 Docker

```bash
sudo apt update
sudo apt install -y docker.io
sudo usermod -aG docker $USER
# 退出 WSL 再进（或 exec su - $USER），让用户组生效
docker run --rm hello-world
```

如果 Docker Hub 拉不动，给 daemon 配镜像加速（可选）：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{ "registry-mirrors": ["https://docker.m.daocloud.io"] }
EOF
sudo systemctl restart docker
```

---

## 3. 安装 fabric-samples + 二进制 + 镜像

Fabric 2.5 的官方安装脚本（默认 Fabric **2.5.16**、Fabric CA **1.5.15**）：

```bash
cd ~
curl -sSLO https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh
chmod +x install-fabric.sh
./install-fabric.sh docker samples binary
# 等价于默认参数；想固定版本：
# ./install-fabric.sh --fabric-version 2.5.16 --ca-version 1.5.15 docker samples binary
```

装完检查：

```bash
ls ~/fabric-samples/bin | head        # peer / orderer / configtxgen / cryptogen ...
ls ~/fabric-samples/test-network
```

> 脚本会 clone `hyperledger/fabric-samples` 到 `~/fabric-samples`，镜像约为 5~8 GB。
> 这一步失败通常是网络问题，重试即可（脚本幂等）。

---

## 4. 起网络 + 建通道

```bash
cd ~/fabric-samples/test-network
./network.sh down          # 先清干净，避免端口/卷冲突
./network.sh up createChannel -c videochannel
```

成功标志：终端最后几行出现 `Channel 'videochannel' created`，以及
`docker ps` 看到 `peer0.org1`、`peer0.org2`、`orderer.example.com` 等容器。

> 参数说明：不加 `-ca` 时用 cryptogen 生成证书（更快）；加 `-ca` 走 Fabric CA（更接近生产，但多 2 个容器、首次启动更慢）。课程作业用默认（cryptogen）即可。

---

## 5. 部署链码（关键：AND 背书策略）

先把链码放到 WSL 自己的**纯 ASCII 路径**下（避免中文路径、也避免 9p 文件系统下 npm install 极慢）：

```bash
cp -r "/mnt/g/AIVideo/双链存证/chaincode/video-evidence" ~/fabric-samples/chaincode/video-evidence
```

如果 `deployCC` 时链码容器里 `npm install` 卡住/失败，在链码目录加一个 `.npmrc`：

```bash
cat > ~/fabric-samples/chaincode/video-evidence/.npmrc <<'EOF'
registry=https://registry.npmmirror.com
EOF
```

部署（**注意 `-ccep` 的大小写和引号**）：

```bash
cd ~/fabric-samples/test-network
./network.sh deployCC \
  -ccn video-evidence \
  -ccv 1.0 \
  -ccs 1 \
  -ccp ~/fabric-samples/chaincode/video-evidence \
  -ccl javascript \
  -ccep "AND('Org1MSP.peer','Org2MSP.peer')"
```

成功标志：最后出现 `Committed chaincode definition for chaincode 'video-evidence'`。

> 常见失败：`-ccp` 必须指向目录（含 package.json），不是文件；`-ccl` 是 `javascript` 不是 `node`；
> 背书策略里 MSP ID 必须和 `configtx.yaml` 里一致（test-network 就是 `Org1MSP` / `Org2MSP`）。

---

## 6. 用 peer CLI 写入 / 查询（AND 策略必须带两个 peer）

```bash
cd ~/fabric-samples/test-network
export PATH=${PWD}/../bin:$PATH
export FABRIC_CFG_PATH=${PWD}/../config/
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_TLS_ROOTCERT_FILE=${PWD}/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt
export CORE_PEER_MSPCONFIGPATH=${PWD}/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp
export CORE_PEER_ADDRESS=localhost:7051
```

写一条存证（注意 `--peerAddresses` 要给**两个组织**，否则收集不到 AND 背书）：

```bash
peer chaincode invoke \
  -o localhost:7050 \
  --ordererTLSHostnameOverride orderer.example.com \
  --tls --cafile "${PWD}/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem" \
  -C videochannel -n video-evidence \
  --peerAddresses localhost:7051 \
  --tlsRootCertFiles "${PWD}/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt" \
  --peerAddresses localhost:9051 \
  --tlsRootCertFiles "${PWD}/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt" \
  -c '{"function":"CreateVideoRecord","Args":["{\"videoId\":\"vid_demo_001\",\"sha256\":\"e7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297\",\"ipfsCid\":\"\",\"ownerId\":\"user_1001\",\"generationParams\":\"{\\\"model\\\":\\\"jimeng\\\",\\\"seed\\\":42}\"}"]}'
```

查询（只读，不需要背书）：

```bash
# 按 videoId 读详情
peer chaincode query -C videochannel -n video-evidence \
  -c '{"function":"ReadVideoRecord","Args":["vid_demo_001"]}'

# 作者视角：查本人全部作品
peer chaincode query -C videochannel -n video-evidence \
  -c '{"function":"QueryRecordsByOwner","Args":["user_1001"]}'

# 平台视角：列全部（limit=100）
peer chaincode query -C videochannel -n video-evidence \
  -c '{"function":"QueryAllRecords","Args":["100"]}'

# 凭文件 SHA-256 反查
peer chaincode query -C videochannel -n video-evidence \
  -c '{"function":"FindVideoIdsBySha256","Args":["e7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297"]}'
```

校验完整性：

```bash
peer chaincode query -C videochannel -n video-evidence \
  -c '{"function":"VerifyExactHash","Args":["vid_demo_001","e7d03a0d0430efad569431b13c0dff92f76457c7cccfaf1ca09f316743347297"]}'
```

> 链码 v2 已删除 `VerifyPerceptualHash`（MVP 不做副本检测）。字段说明见 [`创作信息存证.md`](创作信息存证.md)。

---

## 7. 证明 AND 策略真的生效（答辩加分项，强烈建议做）

```bash
docker stop peer0.org2.example.com
# 再执行一次上面的 invoke → 应报错，关键字：ENDORSEMENT_POLICY_FAILURE / proposal response 不足
docker start peer0.org2.example.com
```

把这两次输出截图/贴进报告，比「我们配置了 AND」有说服力得多。

---

## 8. 跑 bridge，让 Windows 的 Python 调链码

```bash
# WSL 里
cd "/mnt/g/AIVideo/双链存证/bridge"
npm install                   # 首次
export FABRIC_SAMPLES_DIR=$HOME/fabric-samples
node server.js                # 监听 http://127.0.0.1:8801
```

自测（WSL 里另开一个终端）：

```bash
curl -s http://127.0.0.1:8801/health
curl -s -X POST http://127.0.0.1:8801/evaluate \
  -H 'content-type: application/json' \
  -d '{"fn":"ReadVideoRecord","args":["vid_demo_001"]}'
```

Windows 侧：

```powershell
cd G:\AIVideo\双链存证
python python/demo_e2e.py --bridge-url http://127.0.0.1:8801 --no-ipfs
```

> WSL2 默认开启 localhost 转发，Windows 的 `127.0.0.1:8801` 一般能直接打到 WSL 里绑在 127.0.0.1 的服务。
> 如果打不通，把 `server.js` 的 `server.listen(PORT, "127.0.0.1", ...)` 改成 `"0.0.0.0"`，或者直接在 WSL 里跑 demo。

---

## 9. 常见问题对照表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `docker: permission denied` | 用户不在 docker 组 | `sudo usermod -aG docker $USER` 后重新登录 |
| `network.sh up` 卡在拉镜像 | 网络 | 配 registry mirror，或重试（镜像可断点续传） |
| `Channel 'videochannel' not found` | 没建通道 / 通道名不对 | `./network.sh up createChannel -c videochannel` |
| `chaincode install failed` | 链码路径含中文/空格，或缺 package.json | 拷到 `~/fabric-samples/chaincode/` 下纯 ASCII 路径 |
| 链码容器里 `npm install` 超时 | 容器访问 npm registry 慢 | 链码目录加 `.npmrc` 指 npmmirror |
| invoke 报 `ENDORSEMENT_POLICY_FAILURE` | AND 策略只收集到一个组织的背书 | 命令里加第二个 `--peerAddresses`/`--tlsRootCertFiles` |
| bridge 报 `UNAVAILABLE` | peer 没起/端口不对/证书路径错 | `docker ps`、`curl -k https://localhost:7051` 看端口，核对 CRYPTO_PATH |
| bridge 报证书找不到 | 默认路径基于 `$HOME/fabric-samples` | 显式导出 `CRYPTO_PATH` / `TLS_CERT_PATH` / `CERT_PATH` / `KEY_DIR` |
| 磁盘被镜像吃满 | Fabric 镜像 + 3 个链码构建缓存 | `docker system prune`；`./network.sh down` 后清卷 |

---

## 10. 收工清理

```bash
cd ~/fabric-samples/test-network
./network.sh down            # 停容器 + 删网络 + 删加密材料
docker system prune -f       # 可选：清构建缓存
```

下一次演示重新 `./network.sh up createChannel -c videochannel` + `deployCC` 即可
（链码升级记得把 `-ccv`/`-ccs` 递增，Fabric 不允许同版本重复提交）。
