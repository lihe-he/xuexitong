# 8 个开源项目拆解：我们该学什么、该避开什么

> 目标不是"再抄一遍"，而是把别人踩过的坑变成自己的设计约束。
> 下面每条经验后面都标了它落在本项目的哪个模块。

---

## 一、横向对比

| # | 项目 | 形态 | 技术栈 | 覆盖签到类型 | 亮点 | 硬伤 |
|---|------|------|--------|--------------|------|------|
| 1 | [yuban10703/chaoxingsign](https://github.com/yuban10703/chaoxingsign) | CLI | Python | 普通 / 手势 / 位置 / 拍照 | 最早的成熟协议复现，代码短，`requests` 一把梭，好读 | 二维码要人工；接口多年未更新；无并发 |
| 2 | [LnYo-Cly/ChaoXingAutoSign](https://github.com/LnYo-Cly/ChaoXingAutoSign) | CLI | Python | 同上 | 在 ① 基础上修 bug、补超时 | 同样没有监听，靠 cron |
| 3 | [clansty/superstar-checkin](https://github.com/clansty/superstar-checkin) | CLI/Lib | TypeScript | 普通 / 位置 / 二维码 | 类型定义干净，`fetch` 原生 | 功能面窄，缺拍照/签到码 |
| 4 | [AneryCoft/course_helper](https://github.com/AneryCoft/course_helper) | CLI | Python | 签到 + 随堂练习 | 把"课程内所有互动"打通，不止签到 | 随堂练习要题库，维护成本高 |
| 5 | [cxOrz/chaoxing-signin](https://github.com/cxOrz/chaoxing-signin) | **Web + CLI** | Node / React / Koa / MUI | **六种全支持** | **工业级参考**：`pnpm monitor` 监听、IM 协议自动签、QQ 机器人推送、Docker、云函数部署、Termux 支持 | 二维码 enc 仍要人肉；2023 年后作者停更，协议部分过时 |
| 6 | [eric-gitta-moore/chaoxing-sign-app](https://github.com/eric-gitta-moore/chaoxing-sign-app) | App | 多端 | 全类型 | 多账号批量 + 任选照片/位置 | 客户端路线，签名/打包/更新全靠自己扛 |
| 7 | [CofbroTeam/Doraemon](https://github.com/CofbroTeam/Doraemon) | Android | Kotlin | 全类型 + 作业同步 | **UI 体验最好**，作业提醒（Push/短信），一键同步作业 | 必须真机/模拟器常驻，耗电，无法服务器部署 |
| 8 | [aquamarine5/ChaoxingSignFaker](https://github.com/aquamarine5/ChaoxingSignFaker) | Xposed/改包 | Kotlin | 全部 + 人脸 + 签退 + 无限代签 | 能力上限最高：滑块验证码、自定义位置、动态二维码、给别人代签 | **走的是"伪造活动"而不是"完成签到"**，已经从工具滑向作弊，且强依赖 root/框架 |

---

## 二、十条能直接落到代码里的经验

### 1. 协议复现 > UI 自动化

8 个项目里 6 个是纯 HTTP 协议复现，1 个（Doraemon）是 App 内自动化，1 个（Faker）是改包。
**结论**：签到这件事不需要浏览器、不需要 WebView、不需要模拟点击，一个 `httpx.Client` 足够。
→ 本项目：`cxsign/net.py`，零浏览器依赖，可在 32MB 容器里跑。

### 2. 分层必须清楚，否则协议一变全崩

看 ① 的单文件实现最直观：所有 URL、参数、解析混在一起，接口一改就要全局搜索替换。
⑤ 分成 `functions/{user,activity,general,location,qrcode,photo}.ts` + `configs/api.ts`，改起来就只动两处。
→ 本项目：`endpoints.py` 集中存 URL（带 `[稳]/[验]/[推]` 可信度标注），业务层不硬编码任何 URL。

### 3. 签到类型由 `otherId` 决定，`otherId == 0` 时必须再看 `ifphoto`

这是**最高频的翻车点**。`otherId=0` 表示"普通"，但只要活动开了拍照要求，`ifphoto=1`，
你就必须走 `objectId` 分支，否则接口返回 `success` 但**不落库**。
→ 本项目：`activity.classify()` 单独抽出来，配了 14 个参数的单元测试（`tests/test_core.py`）。

### 4. `preSign → analysis → analysis2` 三连不能跳

真实 H5 页面提交前必然先跑这三步，其中 `analysis` 返回的是一段 JS，里面藏着 `code`，
`analysis2` 把它上报回去。**跳过这段，签到可能返回 success 但不计入。**
很多简化实现没写这三步，然后抱怨"签上了但没记录"。⑤ 是全项目里最早踩通这个点的。
→ 本项目：`cxsign/presign.py`，把这条链做成独立模块，并在 `analysis2` 后固定 `sleep(0.5)`（对齐 H5 行为）。

### 5. 监听的本质是轮询，不是长连接

⑤ 用的是 IM 协议（`im.chaoxing.com`）做到秒级，但代价是维护 WebSocket + 心跳 + token 刷新。
相比之下 `activelist` 每 15~25 秒轮询一次，从老师开签到到自己签上通常 20 秒内，**收益/成本比高得多**。
→ 本项目：默认 20 秒轮询（`settings.poll_interval`），IM 留作路线图里的可选增强。

### 6. 登录态会过期，必须有自动续期

所有项目都有"Cookie 过期"的 issue。学习通在登录态失效时会 **302 到 passport2**，不是返回 401。
所以判断标准应该是"是否被重定向"，而不是"状态码是否为 200"。
→ 本项目：`net.request()` 拦截 302 并抛 `AuthExpired`；`engine.ensure_session()` 用保存的密码自动重登并回写 Cookie。

### 7. 二维码 `enc` 是这套协议唯一无法纯服务端解决的缺口

`enc` 只存在于老师屏幕上的动态二维码里，约 30 秒轮换，有时还绑定指定地点。

**八个项目里没有一个"破解"了它**（2026-11 逐个核对源码与 issue）：

| 项目 | 做法 | 是否破解 |
|---|---|---|
| ①② | 人工扫码，把 enc 贴进来 | 否 |
| ⑤ cxOrz | 拍照 / 选图 → 腾讯云 OCR → 识别 enc → 提交 | 否 |
| ⑥ Doraemon | Android 端相机扫码 | 否 |
| ⑦ ⑧ Faker | 现场扫码后给任意账号签 | **否**，README 原话：「需要一台设备在现场扫码」 |
| ⑧ Faker | 手势码 / 签到码 | README 原话：「暂不支持破解」 |

cxOrz 在 issue #178（作者本人回答）给出的两条路，都是"现场拍照 → 识别 → 提交"：

> 1. 配置 QQ 机器人、腾讯 OCR……建议打开 QQ 相机，二维码刷新后立刻按下快门发送，
>    通常 **3 秒内**即可完成签到，图片质量越低识别越快
> 2. Web 页面……选择使用相机，等二维码刷新后立刻按下快门，识别完成点击签到即可

我另外探测了 10 条可能的服务端路径（`/pptSign/getQrCode`、`/newsign/getEnc` 等），
全部 tengine 500 —— 没有任何"凭 activeId 换 enc"的接口。

**结论：能优化的只有延迟，不是绕过。**
→ 本项目：`tools/qr_race.py`，本地 opencv 解码（13ms，不外发）+ 监听缓存定位（0ms）+ enc 池复用。

> 一个悬而未决的矛盾：cxOrz 说「在签到结束前任意时间发送二维码都能签」，
> 但又说二维码 30 秒变换。两者冲突，说明 **enc 的服务端有效期可能远长于显示刷新周期**。
> 本项目保守取 `enc_ttl = 120` 秒，等真实活动时用日志里的 TTL 观测打点校准。

### 8. 位置签到的坐标是 BD-09，不是 WGS-84

传错坐标系会偏 300~600 米，然后接口回你「距离签到位置 512 米」。
坐标系正确后，失败回执里的米数就是最好的自检信号。
→ 本项目：`signer/location.py` 的 `location_distance()` 把米数抽出来直接写进错误信息。

### 9. 固定点位反复签 = 自己给自己留证据

所有学生都传同一个坐标，`getAttendInfo` 里能看到一串完全一致的小数点，很显眼。
→ 本项目：`jitter()` 在 `location_jitter_m` 半径（默认 8 米）内随机偏移，每次不同。

### 10. 开源项目能不能活，取决于"部署成本"和"文档质量"

⑤ 的 README 有 Docker 一行命令、Termux 教程、QQ 机器人配置、UI 截图 —— 这是它 star 最多的真正原因。
① 的 README 只有三段文字。
→ 本项目：Dockerfile + compose + `config.example.toml` + 三个文档 + 一个能点的 Web UI。

---

## 三、明确不做的部分（同时也是给自己留的说明）

| 能力 | ⑧ 的做法 | 本项目的取舍 |
|------|----------|--------------|
| 伪造签到活动 | 本地起一个假活动页/改包，骗过自己客户端 | 不做。签到工具的价值是"完成真实签到"，伪造是另一码事 |
| 人脸签到绕过 | 采集任意人脸图 + 生成 `signToken` | 不做。`FACE` 类型直接返回明确提示 |
| 滑块验证码自动过 | 打码平台 / OCR / 轨迹合成 | 不做。遇到 `validate` 就提示人工，`parse_reply` 已把该回执单独翻译 |
| 给他人代签 | 无限账号批量 | 不做。每个账号必须自己登录、自己保存 Cookie |
| 学习时长/视频进度 | — | 不做。签到和刷课是两个问题，混在一起会让项目定位糊掉 |

这条边界不是"道德洁癖"，是**工程判断**：一旦引入伪造活动和人脸绕过，项目就同时背上了
"随时被判定为作弊工具"和"需要持续对抗风控"两个包袱，维护成本翻十倍，而核心用户（想按时签到的人）并不需要。
