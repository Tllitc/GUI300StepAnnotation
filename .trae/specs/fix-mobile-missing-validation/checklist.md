# Checklist

## 数据保真（两端）

- [x] 安卓 `_build_action_data`：坐标缺失/解析失败时 action_data 无 coordinate/start/end 键，不出现 `[0,0]`
- [x] 安卓：scroll pixels 缺失/非法无 pixels 键（不补 0）；time 缺失/非法无 time 键（不补 1.0）
- [x] 安卓：buttons 仅在有效选择时写入；answer_terminate 仍映射为 "answer"
- [x] iOS `_build_action_data`：坐标/终点/时间/pixels 缺失或非法时对应键整键省略，无 `0`/`[0,0]`/`1.0` 伪造值
- [x] iOS：buttons 仅有效选择时写入；answer_terminate→"answer" 映射保持
- [x] 两端 coords JSON 导出在缺键时不报错、不产生该坐标条目；历史步/草稿回填缺键不崩溃

## 统一校验判定（两端）

- [x] `validate_step_at` 同时支持 live 快照与历史数据，侧栏标记/看板/确认/结束四处结论一致
- [x] click/long_press/type 缺坐标判缺；坐标为 `abc`/NaN/Inf/空 判缺
- [x] swipe/drag 缺起点或终点判缺；vertices 非 4 点或任一点非有限数判缺（不再只看 len==4）
- [x] scroll 缺/非法 pixels 判缺（安卓历史态另收紧为有限整数且排除 bool，0 合法）；TEXT_ACTIONS 空文本判缺；TIME_ACTIONS 缺/非法时间判缺
- [x] system_button 无有效选择判缺（live 读控件、历史读 buttons 有效成员）
- [x] 步骤无关联截图判缺（含历史磁盘文件丢失）；安卓 `_validate_step` 与数据态判定无口径分歧（确认被拦的步，导航离开后结束同样被拦）
- [x] iOS live 判定从"文本非空"升级为数值可解析且有限；`abc` 等不能通过

## 实时联动与缓存失效

- [x] 安卓存在 ~300ms 防抖校验，且连接意图/文本/时间/坐标 x,y/第二坐标/pixels/action_combo/button_combo（keys 一并接入）
- [x] iOS 防抖信号已补连 button_combo
- [x] 两端：补填合法值 300ms 后侧栏"⚠ 缺项"消失、看板计数减 1，无需点确认或切步
- [x] 两端：未确认当前编辑步（current_step==len）的缺项计入看板，并在结束任务时被拦截
- [x] 安卓：上一步/下一步/侧栏跳转/草稿定时落表后被保存下标缺项重算（等长也重算）
- [x] iOS：display_step/go_previous/go_next/jump_to_step/delete/finish 落表后对应下标缺项重算；pending 新步删除后强制重算
- [x] 两端：删除中间步、插入截图步后，后续步骤缺项标记按新下标重算，无错位/无他步原因残留
- [x] 看板不再仅凭"缓存长度==步数"跳过全量重算；iOS `_refresh_item` 等长不再跳过重算

## 重截图 / 截图丢失

- [x] 两端：对已存在步骤重截图覆盖后，旧 vertices/坐标被清除、缺项重算、侧栏刷新、草稿同步
- [x] iOS：草稿/历史步截图文件丢失时进入截图缺项态并提示重截图，动作字段编辑不被静默丢弃

## 结束拦截与落盘

- [x] 两端 `_finish_task`：先保存当前步，再对全部步（含未确认步）统一校验
- [x] wait 缺时间、click 缺坐标、scroll 缺像素、swipe 缺终点、system_button 缺选择五类场景结束均被 ValidationFailDialog 拦截，可跳转目标步
- [x] 有缺项时最终 gui_XXXXXX.json 不写成完成态；补齐复验通过后方可结束
- [x] ValidationFailDialog 中 answer_terminate 步骤显示可区分的"回答并结束"名称

## 文案 / 交互小 bug

- [x] 安卓动作表 answer_terminate 括注英文正确（不再误标 answer）
- [x] iOS terminate 自动填入的"任务完成"意图在切离 terminate 后恢复，不污染其它步骤
- [x] iOS answer 确认后切轮窗口期缺项状态不丢失、不串步（切轮前同步落表/停防抖）
- [x] 安卓 jump_to_step 目标==当前步时有合理反馈（落表+重算而非静默无操作）

## 兼容性与测试

- [x] 含历史默认值（time=1.0、coordinate=[0,0]）的旧草稿/JSON 在新版本可正常打开，不追溯判缺、不崩溃
- [x] 安卓端新增负向 pytest 用例全部通过，且既有测试与 INV 不变量全绿（59 passed）
- [x] iOS 端新增负向 pytest 用例全部通过，且既有测试与 INV-1~INV-10 全绿（63 passed）
- [x] 两端手工冒烟：采一步完整流程（截图→选动作→缺项可见→补填消失→确认/切轮→结束）行为正常（由等价自动化流程用例覆盖：防抖补填、确认/结束拦截、切轮归属、最终落盘一致性）
