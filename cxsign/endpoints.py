"""学习通接口地址表 —— 本项目的核心资产。

按调用链顺序排列。标注说明（2026-11 实测校准）：

* **[稳]** 多个活跃项目长期在用，参数稳定
* **[验]** 本项目对真实服务端探测/调用验证过行为
* **[推]** 仅由 H5 页面行为推断，未验证
* **[✗]** 实测不存在或行为与预期不符，默认不调用

探测结果见 `tools/probe_endpoints.py`。几个容易踩的点：

* `pptSign/stu/checkSignCode` 与 `pptSign/checkSignCode` 都返回 **tengine 500**，
  说明这两个路径在服务端不存在。签到码签到不需要预校验，直接带 `signCode` 提交即可。
* `newsign/preSign` 未登录时跳 ``/widget/mobileError?errormsg=请登录``，**不是** passport2。
* `v2/apis/active/getPPTActiveInfo` 未登录时返回 **200** + ``result:0, errorMsg:"未登录"``。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 登录 / 账号
LOGIN = "https://passport2.chaoxing.com/fanyalogin"                    # [稳] POST
LOGIN_PAGE = "https://passport2.chaoxing.com/mlogin"                    # [稳] GET
ACCOUNT_MANAGE = "https://passport2.chaoxing.com/mooc/accountManage"    # [稳] GET，取真实姓名
PASSPORT_HOME = "https://i.chaoxing.com/base"

# ---------------------------------------------------------------- 课程
COURSE_LIST = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"  # [稳] POST 表单
COURSE_LIST_ALT = "https://mooc1-1.chaoxing.com/visit/courselistdata"          # [稳] 老入口兜底
COURSE_INTERACTION = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
BACK_CLAZZ_DATA = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata"      # [稳] JSON

# ---------------------------------------------------------------- 活动 / 签到
ACTIVE_LIST = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist"   # [验] GET JSON；未登录 302 passport2
ACTIVE_INFO = "https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo"     # [验] GET JSON；未登录 200+result:0
PRE_SIGN = "https://mobilelearn.chaoxing.com/newsign/preSign"                        # [验] GET；未登录 302 /widget/mobileError
ANALYSIS = "https://mobilelearn.chaoxing.com/pptSign/analysis"                       # [验] 返回 $.ajax({...code='+'<32hex>'...})
ANALYSIS2 = "https://mobilelearn.chaoxing.com/pptSign/analysis2"                     # [验] 返回纯文本 success
STU_SIGN_AJAX = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax"              # [验] 未登录返回"请先登录再进行签到"
CHECK_SIGN_CODE = "https://mobilelearn.chaoxing.com/pptSign/stu/checkSignCode"       # [✗] 实测 tengine 500，路径不存在

#: 签到码预校验是否可用。实测不可用，默认关掉；服务端恢复后改成 True 即可
CHECK_SIGN_CODE_WORKS = False

# 群聊（无课程）签到
CHAT_PRE_SIGN = "https://mobilelearn.chaoxing.com/sign/preStuSign"                   # [验] 未登录 200+"用户未登录"
CHAT_SIGN_AJAX = "https://mobilelearn.chaoxing.com/sign/stuSignajax"                 # [验] 未登录 200+"未登陆或其他"

# ---------------------------------------------------------------- 云盘（拍照签到取 objectId）
PAN_HOME = "https://pan-yz.chaoxing.com"                                             # [稳] 解析 enc / _rootdir
PAN_LIST = "https://pan-yz.chaoxing.com/opt/listres"                                 # [稳] POST
PAN_TOKEN = "https://pan-yz.chaoxing.com/api/token/uservalid"                        # [验] 未登录 {"code":-4,"msg":"你没有权限"}
PAN_UPLOAD = "https://pan-yz.chaoxing.com/upload"                                    # [稳] POST multipart

# ---------------------------------------------------------------- 其它
WEBIM_ME = "https://im.chaoxing.com/webim/me"                                        # [验] 未登录 302 passport2/wlogin
MONITOR_HEARTBEAT = "https://detect.chaoxing.com/api/monitor"                        # [稳] 行为打点
