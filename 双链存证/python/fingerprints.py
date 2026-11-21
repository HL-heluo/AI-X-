"""视频双指纹：精确指纹（SHA-256）+ 感知指纹（videohash2）。

本文件是整个双链方案里唯一「不可替代」的计算层：
    · SHA-256 证明「文件一个字节都没改过」；
    · 感知指纹证明「转码/加水印之后还是同一个视频」。

实测（本机，testsrc2 640x360 / 8s / 30fps 生成的样片，videohash2 3.2.2）：

    变体                    汉明距离(bit/64)    默认阈值 10 下判定
    重编码 crf35                  1               相似
    缩放 640→320                  2               相似
    改帧率 30→25                  2               相似
    加水印块                      1               相似
    裁剪 10%                      11              不相似 ← 注意
    旋转 5°                       9               相似
    旋转 90°                      36              不相似
    截取后 6 秒                   12              不相似

另一次实测（testsrc2 320x180 / 3s，缩放到 160x90 并重编码）距离 = 11 bit，
说明**同样的「降一半分辨率」在不同素材上可以是 2 bit，也可能是 11 bit**。
所以：
  1. 感知哈希**绝对不能比相等**（==）。转码一次就翻 1~2 bit。
  2. 默认阈值用 videohash2 自带的 similar_percentage = 15% × 64 bit ≈ 10 bit，
     但它不是金标准：裁剪/换片段/短素材会超过它，必须自己实测校准。
  3. 64 bit 的信息量很小（2^64），生产级方案要更长指纹或关键帧特征匹配。
  4. 合成测试图的绝对值不能外推到真实视频；把实测表替换成你的数据写进报告，
     比抄一份「据说鲁棒」有说服力得多。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile

# videohash2 内部 similar_percentage = 15，对应 ceil(15% * 64) = 10 bit
VIDEOHASH_BITS = 64
MAX_SIMILAR_BITS = 10


def compute_sha256(file_path: str, chunk_size: int = 8192) -> str:
    """精确指纹。分块读，10 GB 的视频也不会把内存吃满。"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def normalize_phash(value: str) -> str:
    """把 videohash2 的几种输出统一成 16 位小写十六进制。

    需要归一化的原因（都是真实踩到的）：
      · `str(VideoHash(...))` 是 '0b' + 64 个 0/1，共 66 字符 —— 不是十六进制；
      · `VideoHash.hash_hex` 是 '0x' + 十六进制，但**开头的 0 会被吃掉**，
        所以长度可能是 15 甚至更短；
      · 链码里存的是定长 16 位十六进制，所以必须先补零。
    """
    if not isinstance(value, str):
        raise TypeError(f"感知哈希必须是字符串，收到 {type(value)!r}")
    s = value.strip().lower()
    if s.startswith("0b"):
        bits = s[2:]
        if len(bits) != VIDEOHASH_BITS or set(bits) - {"0", "1"}:
            raise ValueError(f"二进制感知哈希格式不对：{value!r}")
        return format(int(bits, 2), "016x")
    if s.startswith("0x"):
        s = s[2:]
    if not s or len(s) > 16:
        raise ValueError(f"十六进制感知哈希长度不对：{value!r}")
    if any(c not in "0123456789abcdef" for c in s):
        raise ValueError(f"感知哈希含非十六进制字符：{value!r}")
    return s.zfill(16)


def compute_perceptual_hash(
    video_path: str,
    *,
    storage_path: str | None = None,
    frame_interval: float = 1,
) -> str:
    """感知指纹，返回 16 位小写十六进制（64 bit）。

    两个 Windows 上必须知道的参数：

    · `do_not_copy=False`
      videohash2 默认 `do_not_copy=True`，会用 `os.symlink` 指向原视频。
      Windows 非管理员/未开「开发者模式」时 symlink 直接报
      `OSError: [WinError 1314] 客户端没有所需的特权`。
      传 False 让它复制文件，代价是多占一份磁盘。

    · `storage_path`
      不传的话它会往系统临时目录建一堆帧图/拼贴图，异常时残留。
      自己给一个目录，用完 rmtree，干净。
    """
    from videohash2 import VideoHash  # 延迟导入：只算 SHA-256 时不需要它

    tmp_dir = storage_path or tempfile.mkdtemp(prefix="videohash-")
    owns_dir = storage_path is None
    try:
        vh = VideoHash(
            path=str(video_path),
            storage_path=tmp_dir,
            do_not_copy=False,
            frame_interval=frame_interval,
        )
        # hash_hex 是 '0x...'（可能缺前导零），str(vh) 是 '0b...'；统一归一化
        return normalize_phash(vh.hash_hex)
    finally:
        if owns_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def hamming_distance(a: str, b: str) -> int:
    """两个 16 位十六进制感知哈希之间的汉明距离（0~64）。"""
    x = int(normalize_phash(a), 16) ^ int(normalize_phash(b), 16)
    return bin(x).count("1")


def is_similar(a: str, b: str, max_distance: int = MAX_SIMILAR_BITS) -> bool:
    """感知哈希「相似」判定。默认 10 bit，见文件头的实测表。"""
    return hamming_distance(a, b) <= max_distance


def fingerprint(video_path: str, *, storage_path: str | None = None) -> dict:
    """一次算完两个指纹，返回可直接写进存证记录的 dict。"""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    phash = compute_perceptual_hash(video_path, storage_path=storage_path)
    return {
        "file": os.path.abspath(video_path),
        "sizeBytes": os.path.getsize(video_path),
        "sha256": compute_sha256(video_path),
        "perceptualHash": phash,
        "perceptualBits": VIDEOHASH_BITS,
        "similarThresholdBits": MAX_SIMILAR_BITS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="计算视频的 SHA-256 + 感知哈希")
    parser.add_argument("video", help="视频文件路径")
    parser.add_argument("--compare", help="可选：另一个视频，输出两者的汉明距离")
    args = parser.parse_args()

    result = fingerprint(args.video)
    if args.compare:
        other = compute_perceptual_hash(args.compare)
        result["compare"] = {
            "file": os.path.abspath(args.compare),
            "perceptualHash": other,
            "hammingDistance": hamming_distance(result["perceptualHash"], other),
            "similar": is_similar(result["perceptualHash"], other),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
