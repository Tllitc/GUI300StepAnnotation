# Checklist

## Windows 端（根目录）
- [x] 打开缺失 coords.json 的多轮数据集：仅一条信息性提示，无逐步 mismatch 告警、无状态栏警告追加，coordinate 按 JSON 显示
- [x] 仅改文本保存：最终 JSON 更新，gui 目录不生成 coords.json
- [x] 新拉框保存：最终 JSON coordinate 更新，仍不生成 coords.json
- [x] silent=True 关闭写回：最终 JSON 照常写入，不生成 coords.json
- [x] coords.json 存在但空：按存在处理，不弹缺失提示，B41（0 条告警跳过）不变

## macos 端
- [x] 打开缺失 coords 数据集：仅一条信息性提示，无逐步告警，coordinate 按 JSON 显示
- [x] 仅改文本保存：JSON 更新，不生成 coords.json
- [x] 拉框保存：coordinate 更新，不生成 coords.json
- [x] silent 关闭：JSON 照常写入，不生成 coords.json
- [x] 空文件按存在处理，B41 不变

## ios 端
- [x] 打开缺失 coords 数据集：仅一条信息性提示，无逐步告警，coordinate 按 JSON 显示
- [x] 仅改文本保存：JSON 更新，不生成 coords.json（不走退化框兜底写盘）
- [x] 拉框保存：coordinate 更新，不生成 coords.json
- [x] silent 关闭：JSON 照常写入，不生成 coords.json
- [x] 空文件按存在处理，B41 不变

## 安卓端
- [x] 打开缺失 coords 数据集：仅一条信息性提示，无逐步告警，coordinate 按 JSON 显示
- [x] 仅改文本保存：JSON 更新，不生成 coords.json（不走下标回退写盘）
- [x] 拉框保存：coordinate 更新，不生成 coords.json
- [x] silent 关闭：JSON 照常写入，不生成 coords.json
- [x] 空文件按存在处理，B41 不变

## 回归与不变量
- [x] 含 coords.json 数据集：四端继承/审计/round 注入/文件格式行为不变
- [x] 正常采集、完成、草稿流程与入口按钮行为不变
- [x] 四端全量测试套件全绿