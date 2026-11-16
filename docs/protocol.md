# 学习通签到协议速查

> 本文件是本项目最重要的资产。所有 URL 都集中在 [`cxsign/endpoints.py`](../cxsign/endpoints.py)，
> 业务代码不硬编码地址，接口变更时只改这一个地方。
>
> 标注：**[稳]** 长期稳定 / **[验]** 本项目对生产环境实测验证 / **[推]** 仅推断 / **[✗]** 实测不存在
>
> 2026-11 用 `tools/probe_endpoints.py` 做过一轮实测校准，结果记在下面各节。

---

## 0. 全局

| 项 | 值 |
|---|---|
| 主要域名 | `passport2.chaoxing.com`（登录）、`mooc2-ans.chaoxing.com`（课程）、`mobilelearn.chaoxing.com`（签到） |
| 鉴权方式 | 纯 Cookie，无 token 签名 |
| 关键 Cookie | `_uid`（用户 ID）、`fid`（学校/机构 ID）、`_d`、`vc3`、`uf`、`lv` |
| 建议 UA | 移动端 WebView UA（`mobilelearn` 的签到页是移动 H5） |

### 「未登录」有四种表现，全部实测

这是最容易写错的地方 —— 只认 302 会漏掉一半：

| 接口 | 未登录时的表现 | 判定方式 |
|---|---|---|
| `v2/apis/active/student/activelist` | 302 → `passport2.chaoxing.com/mlogin` | 看 Location |
| `im.chaoxing.com/webim/me` | 302 → `passport2.chaoxing.com/wlogin` | 看 Location |
| `newsign/preSign` | 302 → **`/widget/mobileError?errormsg=请登录…`** | 看 Location，**不是 passport2** |
| `v2/apis/active/getPPTActiveInfo` | **200** + `{"result":0,"data":null,"errorMsg":"未登录或其他"}` | 看 result + errorMsg |
| `pptSign/stuSignajax` | **200** + 纯文本 `请先登录再进行签到` | 看响应体 |
| `sign/stuSignajax` | **200** + `用户未登录` / `未登陆或其他` | 看响应体 |

本项目对应实现：
`net.Session._logged_out_location()`、`activity.is_logged_out_payload()`、
`signer.base.is_logged_out_reply()` —— 三处都有真实报文回归测试（`tests/test_live_payloads.py`）。

**限流特征**：请求过频时返回 **空 JSON / `data: null`**（`result` 仍为 `1`），不是错误码。
要和"未登录"区分开，否则会被误判成掉线并触发重登。

---

## 1. 登录

```
POST https://passport2.chaoxing.com/fanyalogin          [稳]
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
```

| 参数 | 值 |
|---|---|
| `fid` | `-1` |
| `uname` | 手机号 / 用户名（明文） |
| `password` | **加密后**的密码，见下 |
| `refer` | `https%3A%2F%2Fi.chaoxing.com` |
| `t` | `true` |
| `forbidotherlogin` | `0` |
| `validate` | `""`（滑块 token，空表示不需要） |
| `doubleFactorLogin` | `0` |
| `independentId` | `0` |

**密码加密两套方案**（都用，先 AES 失败再 DES）：

| 方案 | 算法 | key | iv | 输出 |
|---|---|---|---|---|
| 主用 | AES-128-CBC + PKCS7 | `u2oh6Vu^HWe4_AES` | 同 key | base64 |
| 兼容 | DES-ECB + PKCS7 | `u2oh6Vu^HWe40fj` | — | 大写 hex |

返回：`{"status": true, "msg2": ...}`，同时 `Set-Cookie` 下发 `_uid` / `fid` / `_d` / `vc3`。
`status=false` 且 `msg2` 提示验证时说明触发了滑块风控，此时无解，只能换 IP / 稍后重试。

**取真实姓名**（签到参数 `name` 用得上）：

```
GET https://passport2.chaoxing.com/mooc/accountManage     [稳]
→ 正则 id="messageName" value="张三"
```

---

## 2. 课程列表

```
POST https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata    [稳]
Content-Type: application/x-www-form-urlencoded
Referer: https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans

courseType=1&courseFolderId=0&courseFolderSize=0
```

返回 HTML 片段，用 `course_(\d+)_(\d+)` 抽出 `(courseId, classId)`。
备用入口：`https://mooc1-1.chaoxing.com/visit/courselistdata`。

> 注意：这个接口对 `Referer` 敏感，漏了会返回空列表。

---

## 3. 活动列表（监听的核心）

```
GET https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist     [稳]
    ?fid={fid}&courseId={courseId}&classId={classId}
    &showNotStartedActive=0&_={毫秒时间戳}
```

返回：

```json
{"result": 1, "data": {"activeList": [
  {"id": 123456789, "nameOne": "签到", "otherId": 0, "status": 1,
   "startTime": 1731731731000, "endTime": 0, "activeSort": 0, "ifphoto": 0}
]}}
```

* `result != 1` → 接口异常
* `data == null` → **请求过频**，必须退避，不能当"没有签到"
* `status == 1` 且 `0 <= otherId <= 5` → 进行中的签到
* `startTime` 是毫秒时间戳；超过 1~2 小时的活动基本已截止

---

## 4. 活动详情

```
GET https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo?activeId={id}   [稳]
```

返回 `data` 对象，关键字段：`otherId`、`ifphoto`、`activeSort`、`nameOne`、`startTime`。

### 类型判定（本项目 `activity.classify()`）

| `otherId` | 类型 | 额外条件 |
|---|---|---|
| 0 | 普通签到 | `ifphoto == 1` 时 **实为拍照签到** |
| 2 | 二维码签到 | 需要 `enc` |
| 3 | 手势签到 | 老师画完手势后自动开放，学生端无需提交额外参数 |
| 4 | 位置签到 | 需要 `address` + `latitude`/`longitude`（BD-09） |
| 5 | 签到码签到 | 需要 `signCode` |

`otherId` 未命中时退回 `activeSort`：5=人脸、6/7/8=二维码（7 约 30 秒轮换）、9=签到码。

---

## 5. 签到前的反作弊链（**不能跳**）

```
1) GET https://mobilelearn.chaoxing.com/newsign/preSign                     [稳]
   ?courseId=&classId=&activePrimaryId={activeId}&general=1&sys=1&ls=1
   &appType=15&tid=&uid={uid}&ut=s

2) GET https://mobilelearn.chaoxing.com/pptSign/analysis                     [验]
   ?vs=1&DB_STRATEGY=RANDOM&aid={activeId}
   → 实测返回（2026-11）：
     $.ajax({type:'get',url:'/pptSign/analysis2?DB_STRATEGY=RANDOM&code='+'a739c0d230f97395c474edc5ee55762e',success:function(res){}});
   → 正则 code\s*=\s*'\+?'([0-9A-Za-z]+)' 取出 32 位 hex code

3) GET https://mobilelearn.chaoxing.com/pptSign/analysis2                    [验]
   ?DB_STRATEGY=RANDOM&code={code}
   → 实测返回纯文本 success

4) sleep 500ms，再提交签到
```

> `analysis` 未登录时**也能拿到 200 + 同样的 JS**（它不校验会话），所以这一步不能用来判断登录态。

`preSign` 返回的页面文本里偶尔带二维码签到的 `enc`（新版页面）。

---

## 6. 提交签到

```
GET/POST https://mobilelearn.chaoxing.com/pptSign/stuSignajax                 [稳]
```

返回 **纯文本**，不是 JSON：

| 回执 | 含义 |
|---|---|
| `success` / `success2` | 成功 |
| `fail` | 失败 |
| `fail-need-qrcode` | 需要二维码 |
| `validate` | 需要滑块验证 |
| `签到失败，请重新扫描` | 二维码 enc 失效 |
| `您已经签到过了` | 重复签到 |
| `距离签到位置 N 米` | 位置超范围（附带真实距离，可用来校正坐标） |

### 公共参数

| 参数 | 说明 |
|---|---|
| `activeId` | 活动 ID |
| `uid` | Cookie 里的 `_uid` |
| `fid` | Cookie 里的 `fid`（也可传 `0`） |
| `courseId` / `classId` | 来自课程列表 |
| `name` | 真实姓名 |
| `clientip` | 空串 |
| `appType` | `15` |
| `useragent` | GET 版本带，POST 版本 H5 不带 |

### 各类型差异

| 类型 | 额外参数 | 动词 |
|---|---|---|
| 普通 | `latitude=-1&longitude=-1` | GET |
| 手势 | 同普通 | GET |
| 签到码 | `+ signCode={码}`（提交前可先 `checkSignCode`） | GET |
| 位置 | `address={地址}&latitude={BD09}&longitude={BD09}&ifTiJiao=1` | GET |
| 拍照 | `objectId={云盘 objectId}&latitude=-1&longitude=-1` | GET |
| 二维码 | `enc={enc}` + 可选 `location={"result":"1","address":"..","latitude":..,"longitude":..,"altitude":100}` | GET |

> `ifTiJiao=1` 是位置签到的关键：不带它，服务端只回距离不落库。

### 签到码预校验：该接口**不存在**

多个第三方库文档（含 `flutter_chaoxing`）提到：

```
GET https://mobilelearn.chaoxing.com/pptSign/stu/checkSignCode?activeId=&signCode=   [✗]
```

2026-11 实测，`/pptSign/stu/checkSignCode` 和 `/pptSign/checkSignCode` 都返回
**tengine 500 Internal Server Error**（Apache 风格的默认错误页），说明路径没有被路由。

结论：**签到码不需要预校验**，直接把 `signCode` 带在 `stuSignajax` 里提交，服务端自己判对错。

本项目 `endpoints.CHECK_SIGN_CODE_WORKS = False`，需要时改这一个开关即可恢复调用。

---

## 7. 拍照签到：云盘

```
GET  https://pan-yz.chaoxing.com/api/token/uservalid          → _token         [稳]
GET  https://pan-yz.chaoxing.com                              → 正则抽 enc、_rootdir  [稳]
POST https://pan-yz.chaoxing.com/opt/listres
     puid=0&shareid=0&parentId={_rootdir}&page=1&size=50&enc={enc}
     → list[].name == "0.jpg"/"0.png" 时取 list[].objectId                     [稳]
POST https://pan-yz.chaoxing.com/upload?_from=mobilelearn&_token={token}
     multipart: file=@x.jpg, puid={uid}   → objectId                            [稳]
```

两条路都支持：手工把图传到云盘根目录命名 `0.jpg`（只查列表），或本地图片自动上传。

---

## 8. 群聊签到（无课程活动）

```
GET  https://mobilelearn.chaoxing.com/sign/preStuSign
     ?activeId=&code=&uid=&courseId=null&classId=0&general=0&chatId=&appType=0&tid=&atype=null&sys=0
GET  https://mobilelearn.chaoxing.com/sign/stuSignajax        （纯签到）
POST https://mobilelearn.chaoxing.com/sign/stuSignajax        （位置签到，表单）
```

`chatId` / `tid` 来自群消息，适合"班群直接发签到"的场景。

---

## 9. 其它有用的接口

| 用途 | 接口 |
|---|---|
| IM 身份（秒级监听用） | `GET https://im.chaoxing.com/webim/me` → `myName` / `myToken` / `myTuid` |
| 学习行为打点 | `GET https://detect.chaoxing.com/api/monitor` |

---

## 10. 坐标系

位置签到用 **BD-09（百度）**，不是 GPS 的 WGS-84，也不是高德的 GCJ-02。

* 取点：[百度坐标拾取](https://api.map.baidu.com/lbsapi/getpoint/index.html)
* 换算（WGS-84 → BD-09）先转 GCJ-02 再加偏移，网上有成熟实现
* 服务端会**原样保存**你提交的坐标（`getAttendInfo` 保留约 7 位小数），
  所以所有人提交同一个点会非常显眼 → 本项目默认加 8 米抖动

---

## 11. 真实环境验证记录（2026-11）

这一节是拿真实账号跑通后补的，都是文档里查不到、只能实测出来的东西。

### 11.1 `vc3` 是硬门槛，而且 JS 拿不到

`document.cookie` 能读到的（17 项）：

```
_uid  UID  fid  _d  uf  xxtenc  cx_p_token  DSSTASH_LOG  _industry
spaceFid  spaceFidEnc  spaceRoleId  space_version  <courseId>cpi/enc/t/ut
```

**缺 `vc3`**。而缺了它，下面这些全部 302 到登录页：

| 接口 | 只带 document.cookie 的结果 |
|---|---|
| `v2/apis/active/student/activelist` | 302 → `passport2.chaoxing.com/mlogin` |
| `v2/apis/active/getPPTActiveInfo` | 200 + `{"result":0,"errorMsg":"未登录或其他"}` |
| `pan-yz.chaoxing.com/api/token/uservalid` | `{"code":-4,"msg":"你没有权限"}` |
| `i.chaoxing.com/base` | 302 → `passport2.chaoxing.com/login?fid=12` |
| `mooc2-ans/visit/courselistdata` | 302 → `passport2.chaoxing.com/login` |

`vc3` 是 **HttpOnly**，JS 读不到。两条正确路径：

1. **Network 面板**：任选一条发往 chaoxing 的请求 → Headers → `Cookie:` 整行（含 HttpOnly）
2. **直接密码登录**：`fanyalogin` 的 `Set-Cookie` 里就带 `vc3`

本项目推荐第 2 条 —— `tools/live_login.py` 一条命令拿全。
登录成功后服务端下发的完整集合（12 项，实测）：

```
_uid  UID  fid  _d  uf  vc3  xxtenc  cx_p_token  DSSTASH_LOG  JSESSIONID  p_auth_token  route
```

### 11.2 姓名不在 `messageName` 里

老文档（含本项目的 v0.1）都写「正则 `id="messageName" value="..."`」。
2026-11 的 `accountManage` 页面**已经没有这个元素**。

现在的结构：

```html
<li>
    <p class="fr colorBlue">
        张三
    </p>姓名
</li>
```

兜底还能从实名认证那行取：

```html
<li><p class="fr color999"><i class="arrowRight fr"></i>张三（已认证）</p>实名认证</li>
```

本项目 `auth.whoami()` 依次尝试 4 种结构，命中即返回。

### 11.3 课程列表必须按块解析

`courselistdata` 返回的可读结构：

```html
<div class="course clearfix  learnCourse stu_300000000"
     info="300000000_900000000" roleId="stu_300000000" id="c_200000000">
  <input type="hidden" class="clazzId"  name="clazzId"  value="300000000"/>
  <input type="hidden" class="courseId" name="courseId" value="200000000"/>
  <span class="course-name overHidden2" title="（2026秋）形势与政策1.3.5">…</span>
  <p class="margint10 line2 color2" title="某某大学">某某大学</p>
  <p class="line2 color3" title="李老师">李老师</p>
</div>
```

**不能全局正则**：`course_(\d+)_(\d+)` 或全局找 `courseId` / `classId`，
在这份 52KB、20 门课的页面上会把 A 课的 `classId` 和 B 课的 `courseId` 配到一起。
必须按 `<div class="course clearfix` 切块，块内取三个值。

### 11.4 其它确认

* `activelist` 在没有任何进行中活动时返回 `{"result":1,"data":{"activeList":[]}}`（不是 null）
* 20 门课全量扫描耗时约 3~5 秒（并发 3），未触发限流
* 登录后 `validate()` 走 `courselistdata` 判定，页面长度 52KB 左右，远大于 2000 字节阈值
* `JSESSIONID` 与 `p_auth_token` 也是登录后新出现的，但只带口令式 cookie 时不必要

---

## 12. 二维码签到：能做什么、不能做什么

### 12.1 服务端没有"凭 activeId 换 enc"的接口

2026-11 逐条探测，全部返回 **tengine 500**（路径不存在）：

```
/pptSign/getQrCode      /pptSign/getQRCode      /pptSign/qrcode
/pptSign/stu/getEnc     /pptSign/getEnc         /newsign/getEnc
/newsign/qrcode         /v2/apis/active/getQRCode
/v2/apis/active/getQrCode                       /pptSign/stu/qrcode
```

结论：**enc 无法凭空生成，也无法服务端获取**。它只存在于老师屏幕的那张图里。
复现脚本见 `tools/probe_qr_endpoints.py`。

### 12.2 enc 过期后签不上，但它**不绑学生**

| 问题 | 答案 |
|---|---|
| 过期后能签上吗 | **不能**。服务端会返回 `签到失败，请重新扫描` |
| 能不能伪造 enc | 不能。格式像随机串（28 位字母数字），服务端做的是查表校验 |
| 同一个 enc 能签多个人吗 | **能**。它不是按学生签发的，老师屏幕上那一张全班通用 |
| 能不能靠 activeId 推导 | 不能，见 12.1 |

所以"破解"在工程上不是伪造，而是三件事：**抢时间**、**共享**、**复用**。

### 12.3 抢时间窗的工程实现

`tools/qr_race.py` 把「截图 → 解码 → 提交」压到一条流水线：

```bash
# 监听目录：手机截屏同步到电脑，落盘即抢
python tools/qr_race.py --dir data/qr

# 单张图
python tools/qr_race.py --once shot.png

# 已知活动，零扫描（最快）
python tools/qr_race.py --once shot.png --active <activeId> --course <courseId> --class-id <classId>
```

实测耗时分解（本地）：

| 阶段 | 耗时 |
|---|---|
| opencv 解码二维码 | **13~14 ms** |
| 定位活动（读监听缓存） | **0 ms** |
| 定位活动（缓存未命中，全量扫 20 门课） | ~10000 ms |
| 提交 `stuSignajax` | 视网络 300~1500 ms |

两个关键优化：

1. **目标缓存**：监听每 20 秒扫一遍，扫到二维码活动就写进 `kv(qrtarget:*)`。
   抢签器直接读，省掉 10 秒全量扫描。
2. **提交不重试**：`stuSignajax` 遇到 5xx 立刻返回而不是重试 3 次
   —— 重试会把有效的 enc 拖到过期。

### 12.4 enc 会缓存多久

`enc` 一旦拿到就写进 `kv(enc:<activeId>)`，默认 `enc_ttl = 120` 秒内可复用。
这样同一门课多个账号只需要捕获一次。

每次签到成功都会打印实际年龄：

```
      └ enc 缓存 47s 后仍有效（TTL 观测）
```

积累几次真实数据后就能把 `enc_ttl` 调准。目前保守取 120 秒。
