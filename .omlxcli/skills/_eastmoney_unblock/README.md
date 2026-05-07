# EastMoney Auto Unblock

内置的东财封控自动解除脚本，来源于 `eyu-ip-pool` 的 bypass 方案。

运行链路：

1. `pass.js` 获取 `contextid` 与滑块 challenge
2. 调用 `gen_track.py`（OpenCV 模板匹配）生成位移与轨迹
3. 提交 `Validate` + `valid` 完成解封

依赖：

- `node`（用于运行 `pass.js`）
- `python3`
- Python 包：`opencv-python`、`numpy`、`requests`、`Pillow`

