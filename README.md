# KTV-MV-AI 伴奏分离-
自动进行人声/伴奏分离、响度统一和双音轨封装，让普通 MV 转换为可切换“原唱 / 伴奏”的家庭 KTV 视频。

# UVR5 KTV MV Maker

> 基于 UVR / RoFormer + FFmpeg 的批量 KTV MV 制作工具
> 自动进行人声/伴奏分离、响度统一和双音轨封装，让普通 MV 转换为可切换“原唱 / 伴奏”的家庭 KTV 视频。

---

## 简介

**UVR5 KTV MV Maker** 是一个使用 Python + PySide6 开发的桌面 GUI 工具。

程序可以批量读取单个 MV 或整个 MV 文件夹，使用 **UVR / RoFormer / MDX-Net** 等音源分离模型生成高质量伴奏，然后通过 FFmpeg 将：

* 原始 MV 视频；
* 原唱音频；
* UVR 分离后的伴奏音频；

重新封装为适用于家庭 KTV 系统的双音轨视频。

默认输出：

```text
Video   = 原始 MV 视频
Audio 1 = 原唱
Audio 2 = 伴奏
```

播放时只需要切换音轨，即可实现：

```text
原唱 ⇄ 伴奏
```

同时项目加入了基于 **EBU R128 / LUFS** 的响度统一机制，可以显著减少：

* 不同歌曲之间音量忽大忽小；
* 原唱与伴奏切换时音量突变；
* 不同来源 MV 响度不一致；

等问题。

---

# Features

## UVR 音源分离

通过 `python-audio-separator` 调用 UVR 生态模型，支持包括：

```text
MelBand RoFormer
BS-RoFormer
MDX-Net
UVR-MDX-NET
```

等模型。

推荐 KTV 使用：

```text
mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt
```

该类模型更偏向：

```text
Original Mix
      │
      ▼
  UVR / RoFormer
      │
      ├──────────────► Vocals
      │
      └──────────────► Instrumental
```

本项目主要使用 `Instrumental` 作为 KTV 伴奏轨。

---

## 批量 MV 处理

支持：

* 单个 MV；
* 多个 MV；
* 整个目录；
* 递归扫描子目录；
* 保留原始目录结构；
* 批量任务队列；
* 独立任务进度；
* 总体处理进度；
* 任务失败不中断其他视频；
* 支持取消任务。

常见视频格式：

```text
.mp4
.mkv
.mov
.avi
.wmv
.flv
.ts
.m2ts
.mpg
.mpeg
.vob
.webm
.m4v
.mts
```

---

## KTV 双音轨封装

默认采用：

```text
轨道 1：原唱
轨道 2：伴奏
```

并写入音轨名称：

```text
Audio 1
title = 原唱

Audio 2
title = 伴奏
```

默认：

```text
Audio 1 = Default
```

可以在 GUI 中修改为：

```text
轨道 1：伴奏
轨道 2：原唱
```

以兼容不同家庭 KTV 点歌系统。

---

## 左右声道 KTV 模式

部分传统点歌机并不支持多音轨，而是通过左右声道控制原唱 / 伴奏。

因此项目同时支持：

```text
Left  = 伴奏
Right = 原唱
```

或者：

```text
Left  = 原唱
Right = 伴奏
```

适用于部分传统 KTV 设备。

---

# Loudness Normalization

不同来源 MV 的音量差异可能很大。

例如：

```text
歌曲 A：-12 LUFS
歌曲 B：-20 LUFS
歌曲 C：-15 LUFS
```

如果直接加入家庭 KTV 曲库，会造成切歌时明显的音量变化。

本项目增加了基于：

```text
EBU R128
LUFS
True Peak
FFmpeg loudnorm
```

的响度均衡机制。

处理流程：

```text
固定参考曲目
      │
      ▼
分析 Integrated Loudness
      │
      ▼
获得参考 LUFS
      │
      ├─────────────────┐
      ▼                 ▼
   原唱轨             伴奏轨
      │                 │
      ▼                 ▼
两遍 loudnorm       两遍 loudnorm
      │                 │
      └────────┬────────┘
               ▼
         响度一致的双音轨
```

程序会分别分析：

```text
原唱
伴奏
```

而不是简单对两条音轨使用相同增益。

这样可以尽可能保证：

```text
原唱 ⇄ 伴奏
```

切换时主观响度基本一致。

---

## Reference Track

程序支持使用固定的响度参考音频。

之后处理的所有歌曲都会以该参考音频的 Integrated Loudness 为目标进行归一。

你也可以使用自己的参考曲目，例如选择一首已经在家庭 KTV 中试听并确认音量合适的歌曲。

推荐原则：

* 动态范围正常；
* 不存在严重削波；
* 音量符合日常 KTV 使用习惯；
* 不使用异常响亮的 Loudness War 母带作为参考。

---

# Video Processing

## 默认不重新编码视频

默认：

```text
-c:v copy
```

也就是说：

> 只处理音频，不重新压缩视频。

优点：

* 不损失画质；
* 速度快；
* CPU / GPU 占用低；
* 4K MV 也可以快速重新封装。

---

## 可选视频重新编码

如果家庭 KTV 点歌机只支持特定编码，也可以开启视频重新编码。

支持：

```text
libx264
libx265
h264_nvenc
hevc_nvenc
```

可以设置：

```text
Preset
CRF / CQ
Bitrate
Pixel Format
Additional FFmpeg Parameters
```

例如老设备需要：

```text
H.264
yuv420p
AAC
MP4
```

就可以开启：

```text
Codec:
libx264

Pixel Format:
yuv420p
```

重新生成兼容性更好的 MV。

---

# File Naming

默认：

> 保持原文件名不变。

例如：

```text
输入：

周杰伦 - 晴天.mp4
```

输出：

```text
周杰伦 - 晴天.mp4
```

不会自动添加：

```text
_KTV
```

如果输出目录和输入目录相同，为避免覆盖源文件，程序会采取安全命名策略。

同时支持：

```text
覆盖
跳过
自动改名
```

三种文件冲突处理方式。

---

# Model Integrity Check

UVR 模型通常有数百 MB，甚至接近 1 GB。

网络异常时可能出现：

```text
模型文件只有几 KB
HTML 错误页面
Git-LFS Pointer
下载中断
checkpoint 损坏
```

旧版本可能会直到 PyTorch 加载模型时才发现问题。

当前版本增加了模型预检流程：

```text
启动批处理
    │
    ▼
检查模型文件
    │
    ├─ 文件不存在
    ├─ 文件异常小
    ├─ HTML
    ├─ Git-LFS Pointer
    └─ checkpoint 异常
          │
          ▼
     自动重新下载
          │
          ▼
      完整性检查
          │
          ▼
        UVR 推理
```

对于部分预设模型还可以进行：

```text
SHA-256
```

校验。

---

# Workflow

完整工作流程：

```text
                 ┌───────────────────┐
                 │      MV Input      │
                 └─────────┬─────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │ FFprobe Validation │
                 └─────────┬─────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │ FFmpeg Extract     │
                 │ Original Audio     │
                 └─────────┬─────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │ UVR / RoFormer     │
                 │ Source Separation  │
                 └─────────┬─────────┘
                           │
                  ┌────────┴────────┐
                  ▼                 ▼
              Original         Instrumental
                  │                 │
                  ▼                 ▼
             Loudness          Loudness
           Normalization     Normalization
                  │                 │
                  └────────┬────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │   FFmpeg Muxing    │
                 └─────────┬─────────┘
                           │
                           ▼
                 ┌───────────────────┐
                 │     KTV MV         │
                 │ Audio 1 = Original │
                 │ Audio 2 = Karaoke  │
                 └───────────────────┘
```

---

# Requirements

推荐环境：

```text
Windows 10 / Windows 11
Python 3.10 / 3.11
PyCharm
FFmpeg
```

GPU 推荐：

```text
NVIDIA GPU
```

RoFormer 等大型模型使用 GPU 时速度会明显高于 CPU。

CPU 也可以运行，但模型推理速度可能很慢。

---

# Installation

## 1. Clone Repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd uvr5_ktv_maker
```

或者直接下载：

```text
Code
→ Download ZIP
```

---

# PyCharm Setup

## 2. Open Project

PyCharm：

```text
File
→ Open
→ uvr5_ktv_maker
```

确认项目根目录可以看到：

```text
run.py
requirements.txt
ktv_maker/
resources/
```

---

## 3. Create Virtual Environment

建议：

```text
Python 3.10
```

或者：

```text
Python 3.11
```

PyCharm：

```text
File
→ Settings
→ Project
→ Python Interpreter
→ Add Interpreter
→ Virtualenv
```

例如：

```text
uvr5_ktv_maker/
└─ .venv/
```

---

## 4. Install GUI Dependencies

打开 PyCharm Terminal：

```bash
python -m pip install --upgrade pip setuptools wheel
```

然后：

```bash
python -m pip install -r requirements.txt
```

---

# Install audio-separator

## NVIDIA GPU

推荐：

```bash
python -m pip install "audio-separator[gpu]"
```

检查：

```bash
audio-separator --env_info
```

也可以检查 PyTorch：

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

正常情况下：

```text
True
```

查看 GPU：

```bash
python -c "import torch; print(torch.cuda.get_device_name(0))"
```

---

## CPU

如果没有 NVIDIA GPU：

```bash
python -m pip install "audio-separator[cpu]"
```

或者：

```bash
python -m pip install audio-separator
```

---

# Install FFmpeg

项目必须能够调用：

```text
ffmpeg
ffprobe
```

Windows 可以下载 FFmpeg 后得到：

```text
C:\ffmpeg\bin\ffmpeg.exe
C:\ffmpeg\bin\ffprobe.exe
```

在 Terminal 测试：

```bash
ffmpeg -version
```

```bash
ffprobe -version
```

如果不想修改 Windows PATH，可以直接在 GUI 中填写：

```text
C:\ffmpeg\bin\ffmpeg.exe
```

程序会优先寻找同目录中的：

```text
ffprobe.exe
```

---

# Run

程序入口：

```text
run.py
```

在 PyCharm 中：

```text
右键 run.py
→ Run 'run'
```

也可以：

```bash
python run.py
```

---

# Basic Usage

## Step 1 — Add MV

点击：

```text
添加文件
```

或者：

```text
添加目录
```

目录模式支持：

```text
递归搜索
```

---

## Step 2 — Select Output Directory

例如：

```text
D:\KTV_MV
```

---

## Step 3 — Select UVR Model

推荐：

```text
mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt
```

模型第一次运行时可能需要下载。

模型文件通常较大，因此第一次使用需要等待模型下载完成。

---

## Step 4 — Configure Loudness

推荐启用：

```text
Loudness Normalization
```

然后：

```text
Reference Audio
```

选择：

```text
Built-in Reference
```

或者指定自己的固定参考曲目。

建议同时开启：

```text
True Peak Protection
```

---

## Step 5 — Configure Audio Tracks

默认：

```text
Track 1 = Original
Track 2 = Instrumental
```

也可以根据点歌机要求反转。

---

## Step 6 — Video Encoding

一般情况下保持：

```text
Video Codec = Copy
```

只有设备兼容性存在问题时才开启重新编码。

---

## Step 7 — Environment Check

第一次运行前建议点击：

```text
环境检测
```

检查：

```text
FFmpeg
FFprobe
audio-separator
UVR Model
PyTorch
CUDA
ONNX Runtime
```

---

## Step 8 — Start

点击：

```text
开始批量制作
```

日志会显示类似：

```text
[预检] FFmpeg OK
[预检] UVR 模型 OK

[1/5] 提取音频
[2/5] UVR 分离
[3/5] 原唱响度归一
[4/5] 伴奏响度归一
[5/5] KTV 封装

完成
```

---

# Progress

GUI 使用结构化进度，而不是默认输出大量 FFmpeg 信息。

例如：

```text
提取音频           8%
UVR 分离          42%
原唱响度处理      67%
伴奏响度处理      82%
视频封装          96%
输出验证         100%
```

需要排查问题时，可以开启：

```text
详细日志
```

查看 FFmpeg / UVR 原始输出。

---

# Output

例如：

```text
Input:

D:\MV\
├─ 周杰伦 - 晴天.mp4
├─ 林俊杰 - 小酒窝.mp4
└─ 蔡依林 - 说爱你.mp4
```

输出：

```text
D:\KTV\
├─ 周杰伦 - 晴天.mp4
├─ 林俊杰 - 小酒窝.mp4
└─ 蔡依林 - 说爱你.mp4
```

每个文件内部：

```text
Video 0
└─ Original Video

Audio 1
└─ 原唱

Audio 2
└─ 伴奏
```

---

# Verify Output

项目提供：

```text
tools/inspect_ktv.py
```

检查音轨：

```bash
python tools/inspect_ktv.py "D:\KTV\周杰伦 - 晴天.mp4"
```

如果需要同时检查响度：

```bash
python tools/inspect_ktv.py "D:\KTV\周杰伦 - 晴天.mp4" --loudness
```

可以检查：

```text
Video Codec
Audio Streams
Track Name
Channel Count
Integrated Loudness
```

---

# Project Structure

```text
uvr5_ktv_maker/
│
├─ run.py
├─ requirements.txt
├─ README.md
│
├─ resources/
│  └─ loudness_reference.wav
│
├─ ktv_maker/
│  │
│  ├─ app.py
│  │
│  ├─ core/
│  │  ├─ media.py
│  │  ├─ model_manager.py
│  │  ├─ loudness.py
│  │  ├─ models.py
│  │  ├─ muxer.py
│  │  ├─ pipeline.py
│  │  ├─ separator.py
│  │  └─ utils.py
│  │
│  └─ ui/
│     ├─ main_window.py
│     └─ worker.py
│
└─ tools/
   └─ inspect_ktv.py
```

---

# Troubleshooting

## `audio-separator` not found

执行：

```bash
python -m pip show audio-separator
```

Windows Virtualenv 通常位于：

```text
<project>\.venv\Scripts\audio-separator.exe
```

可以在 GUI 中直接填写该路径。

---

## CUDA is not available

执行：

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

如果：

```text
False
```

说明当前 PyTorch 没有正确启用 CUDA。

检查：

* NVIDIA Driver；
* PyTorch CUDA Build；
* 当前 PyCharm Interpreter；
* audio-separator 安装环境。

---

## Model checkpoint corrupted

常见错误：

```text
PytorchStreamReader failed reading zip archive
failed finding central directory
```

通常表示模型：

```text
下载失败
文件不完整
被代理替换
Git-LFS 文件异常
```

当前版本会在批处理开始前检查模型，并尝试自动修复。

---

## ONNX CUDA DLL Error

例如：

```text
cublas64_12.dll not found
cudart64_12.dll not found
```

如果当前使用的是：

```text
.ckpt
RoFormer
```

模型主要通过 PyTorch 工作，该错误未必会影响当前模型。

如果使用：

```text
.onnx
```

则需要正确配置：

```text
ONNX Runtime
CUDA
cuDNN
```

版本。

---

## Output Cannot Be Played on KTV Device

不同家庭 KTV 系统的支持格式差异很大。

可以尝试将视频重新编码为：

```text
Container:
MP4

Video:
H.264

Pixel Format:
yuv420p

Audio:
AAC
```

这是兼容性较高的组合。

---

# KTV Compatibility

家庭 KTV 系统通常存在三种实现。

## Multi-Audio Track

```text
Audio 1 = Original
Audio 2 = Instrumental
```

这是本项目默认方式。

---

## Left / Right Channel

```text
Left  = Instrumental
Right = Original
```

项目也支持这种方式。

---

## Vendor-Specific Library

部分商业点歌机还要求：

```text
Song ID
Singer ID
Database
Cover
Lyrics
Private Directory Structure
Special Filename
MPEG-TS
```

这些属于具体厂商的曲库协议，并不是标准 MP4/MKV 音轨封装的一部分。

本项目目前主要负责：

> 生成标准的原唱 / 伴奏可切换 KTV 视频文件。

---

# Performance

UVR / RoFormer 是整个工作流中计算量最大的部分。

性能主要取决于：

```text
GPU
VRAM
UVR Model
Song Duration
Model Architecture
```

4K MV 不一定会显著增加 UVR 分离时间，因为程序首先提取音频，UVR 主要处理音频数据。

视频默认：

```text
-c:v copy
```

因此即使是 4K MV，最终封装通常也比较快。

---

# Notes

源分离并不是完全可逆过程。

伴奏质量可能受到以下因素影响：

* 和声；
* 混响；
* 现场版；
* 观众声；
* 人声与乐器频率高度重叠；
* 压缩失真；
* 老录音；
* 特殊立体声混音。

对于 KTV 场景，建议使用专门优化的：

```text
Karaoke RoFormer
```

模型。

---

# Roadmap

后续可以继续增加：

* [ ] 多模型自动质量比较；
* [ ] 批量歌曲响度统计；
* [ ] GPU 显存自适应参数；
* [ ] Intel / AMD GPU 加速；
* [ ] KTV 曲库数据库生成；
* [ ] 自动识别歌手 / 歌名；
* [ ] LRC 歌词匹配；
* [ ] MV 元数据编辑；
* [ ] 封面生成；
* [ ] 多 GPU 批处理；
* [ ] Docker 部署；
* [ ] NAS 自动扫描；
* [ ] Web 管理界面。

---

# Contributing

欢迎提交：

```text
Issues
Pull Requests
Feature Requests
Bug Reports
```

如果提交 Bug，建议附带：

```text
Operating System
Python Version
GPU
PyTorch Version
audio-separator Version
FFmpeg Version
UVR Model
Complete Error Log
```

这样更容易定位问题。

---

# Disclaimer

本项目仅提供：

* 音频源分离；
* 响度处理；
* 视频重新封装；
* KTV 媒体制作；

等技术功能。

请仅处理你拥有合法使用权、个人使用权或已获得授权的视频和音频内容。

用户应自行遵守所在地区的版权及相关法律法规。

---

# Acknowledgements

本项目使用或依赖以下优秀的开源生态：

* Ultimate Vocal Remover / UVR ecosystem
* python-audio-separator
* FFmpeg
* PyTorch
* ONNX Runtime
* PySide6

感谢相关项目开发者与开源社区。

---

## ⭐ Star

如果这个项目对你的家庭 KTV 曲库制作有所帮助，欢迎给项目一个 **Star**。

也欢迎提交 Issue 分享不同家庭 KTV 点歌系统的：

```text
音轨要求
视频格式
编码要求
文件命名规则
```

以进一步完善兼容性。
