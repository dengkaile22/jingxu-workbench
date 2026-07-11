# test-assets（本地客户素材）

本目录存放**真机验收**用客户视频（如 `桌面风扇/`、`赵雨蒙版/`），由集成测试 `CustomerAssetAcceptanceTests` 按需发现。

## Git 策略

- 目录内媒体文件（`.mp4` 等）与仓库根目录的 `.rar` **不纳入版本控制**（见根 `.gitignore`）。
- 本 `README.md` 可跟踪，用于说明布局期望。
- 缺少素材时验收测试会 `Assert.Skip`，不影响常规单元/ lavfi 集成测试。

## 建议布局

```text
test-assets/
  桌面风扇/桌面风扇/1.mp4 … 8.mp4
  赵雨蒙版/赵雨 (8).mp4
```

解压客户压缩包后放到上述路径即可；根目录重复的 `.rar` 可在确认解压完整后删除。
