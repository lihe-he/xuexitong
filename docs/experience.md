# 参考项目与借鉴

> 这个领域已经有不少人做过探索。做设计之前我把它们逐个读了一遍，
> 下面记的是**我从中采用的做法**，以及每条落在本项目的哪个模块。
>
> 没有一句是"别人做错了"—— 每个项目都在解决它当时的场景，
> 我只是把可复用的部分拿过来。

---

## 一、参考项目

| # | 项目 | 形态 | 技术栈 | 覆盖 | 我借鉴了什么 |
|---|------|------|--------|------|--------------|
| 1 | [yuban10703/chaoxingsign](https://github.com/yuban10703/chaoxingsign) | CLI | Python | 普通 / 手势 / 位置 / 拍照 | 最早的成体系协议记录，代码短、一个文件读完，适合入门 |
| 2 | [LnYo-Cly/ChaoXingAutoSign](https://github.com/LnYo-Cly/ChaoXingAutoSign) | CLI | Python | 同上 | 超时与重试的处理方式 |
| 3 | [clansty/superstar-checkin](https://github.com/clansty/superstar-checkin) | CLI / Lib | TypeScript | 普通 / 位置 / 二维码 | 类型定义干净，接口模型清晰 |
| 4 | [AneryCoft/course_helper](https://github.com/AneryCoft/course_helper) | CLI | Python | 签到 + 随堂练习 | 把"课程内所有互动"打通的思路 |
| 5 | [cxOrz/chaoxing-signin](https://github.com/cxOrz/chaoxing-signin) | Web + CLI | Node / React / Koa | 六种全支持 | **参考价值最高**：`monitor` 监听模式、IM 协议、QQ 机器人、Docker 与云函数部署、Termux 方案 |
| 6 | [eric-gitta-moore/chaoxing-sign-app](https://github.com/eric-gitta-moore/chaoxing-sign-app) | App | 多端 | 全类型 | 多账号批量操作的组织方式 |
| 7 | [CofbroTeam/Doraemon](https://github.com/CofbroTeam/Doraemon) | Android | Kotlin | 全类型 + 作业同步 | 交互设计：活动提醒做到 Push / 短信级别 |
| 8 | [aquamarine5/ChaoxingSignFaker](https://github.com/aquamarine5/ChaoxingSignFaker) | Android | Kotlin | 全部 + 人脸 + 签退 | 展示了这套协议的能力上限在哪 |

---

## 二、十条落进代码里的结论

### 1. 协议复现优于界面驱动

这 8 个里 6 个是纯 HTTP 协议复现，1 个是 App 内自动化，1 个是改包。
签到本质是一次表单提交，不需要渲染任何页面。

→ 本项目：`cxsign/net.py`，零浏览器依赖，可以塞进 32MB 容器。

### 2. 分层必须清楚，否则协议一变全崩

把 URL、参数、解析混在一个文件里，接口一改就要全局搜索替换。
把 `functions/{user,activity,general,location,qrcode,photo}` 和 `configs/api.ts` 拆开，
改起来只动两处。

→ 本项目：`endpoints.py` 集中存 URL（带 `[稳]/[验]/[推]/[✗]` 可信度标注），业务层不硬编码。

### 3. 签到类型由 `otherId` 决定，`otherId == 0` 时必须再看 `ifphoto`

`otherId=0` 表示"普通"，但只要活动开了拍照要求，`ifphoto=1`，就必须走 `objectId` 分支，
否则接口返回 `success` 但**不落库**。

这是最容易踩的一个点，所以本项目把它单独抽成纯函数并配了 14 条用例。

→ 本项目：`activity.classify()` + `tests/test_core.py`

### 4. `preSign → analysis → analysis2` 三连不能跳

真实 H5 页面提交前必然先跑这三步，其中 `analysis` 返回一段 JS，里面藏着 `code`，
`analysis2` 把它上报回去。跳过这段，签到可能返回 success 但不计入。

→ 本项目：`cxsign/presign.py`，并在 `analysis2` 后固定 `sleep(0.5)` 对齐 H5 行为。

### 5. 监听做成轮询，成本最低

IM 协议能做到秒级，代价是维护 WebSocket + 心跳 + token 刷新。
`activelist` 每 15~25 秒轮询一次，从老师开签到到自动签上通常 20 秒内，
收益/成本比高得多。

→ 本项目：默认 20 秒轮询，IM 留作 `docs/roadmap.md` 里的可选增强。

### 6. 登录态会过期，必须能续期

学习通在登录态失效时会 **302 到 passport2**，不是返回 401。
所以判定标准应该是"是否被重定向"，而不是"状态码是否为 200"。

→ 本项目：`net.request()` 拦截 302 抛 `AuthExpired`；`engine.ensure_session()` 用保存的密码自动重登并回写 Cookie。

### 7. 二维码 `enc` 只能靠现场拿到

`enc` 只存在于老师屏幕上的动态二维码里，约 30 秒轮换。它能被拍照识别，
但服务端没有任何"凭 activeId 换 enc"的接口（实测 10 条候选路径全部 tengine 500）。

所以能优化的只有**延迟**，不是绕过。

→ 本项目：`tools/qr.py`，本地 opencv 解码（13ms）+ 目标缓存定位（0ms）+ enc 池复用。
不接任何在线打码平台。

### 8. 位置签到的坐标是 BD-09

不是 GPS 的 WGS-84，也不是高德的 GCJ-02。传错会偏 300~600 米，
失败回执里的「距离签到位置 N 米」就是最好的自检信号。

→ 本项目：`signer/location.py` 把米数抽出来直接写进错误信息。

### 9. 固定点位反复签很显眼

所有学生传同一个坐标，`getAttendInfo` 里能看到一串完全一致的小数点。

→ 本项目：`jitter()` 在 `location_jitter_m` 半径（默认 8 米）内随机偏移。

### 10. 部署成本和文档质量决定项目能不能被用起来

一行 Docker 命令、配置模板、能点的 Web UI、把踩过的坑写进文档 ——
这些比多支持一种签到类型更能决定别人愿不愿意试。

→ 本项目：Dockerfile + compose + `config.example.toml` + 5 份文档 + 单页 UI。

---

## 三、边界

有几件事这 8 个项目里做法不一，本项目选择不做：

| 能力 | 本项目的取舍 |
|---|---|
| 伪造签到活动 | 不做。签到工具的价值是"完成真实签到" |
| 人脸签到绕过 | 不做，遇到直接返回明确提示 |
| 滑块验证码自动过 | 不做，遇到 `validate` 就提示人工 |
| 刷视频时长 / 章节 | 不做，与项目定位无关 |
| 作业答案 / 题库 | 不做，同上 |

代签不在这个列表里 —— 它是"多账号 + 授权模型 + 身份隔离"的工程问题，
方案见 [delegation.md](delegation.md)。

---

## 致谢

上面这些项目把协议摸清了，才有了后来者的起点。如果这个项目里有什么地方做得还行，
多半是从它们那儿学来的；做得不好的地方，是我自己的问题。
