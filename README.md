# Toolbag5 BatchRender

Marmoset Toolbag 5 的 Python 批量渲染插件：按场景大纲中的“文件夹”依次显示/隐藏，
用指定摄像机逐一渲染，并以文件夹名称命名输出图片。

## 文件

- `batch_render_by_folder.py` — 插件主体，可直接放入 Toolbag 的 Plugins 目录使用，
  也可以作为普通脚本加载运行。

## 安装 / 运行

1. **作为插件安装（推荐）**：
   Toolbag 菜单 `Help > Show Plugins Folder`，把 `batch_render_by_folder.py`
   复制进去，重启 Toolbag，在 Plugins 菜单里点击即可打开批量渲染面板。
2. **作为脚本运行**：
   打开 Toolbag 的 Scripting 面板，选择 `Load Script` 加载本文件运行。

## 使用方式

运行后会弹出浮动面板，依次填写：

- **摄像机**：从检测到的所有摄像机中选择一个用于渲染。
- **父级文件夹**（可留空）：留空表示从“场景根目录”开始递归扫描；填写某个
  已有对象名称，则只从该对象开始往下递归扫描。文件夹可以任意嵌套多层，
  脚本会递归找到整棵树里的所有文件夹。
- **Leaf Folders Only**（默认勾选）：只渲染“叶子”文件夹，即自身不再包含
  子文件夹的那一级——这才是真正对应“一个变体”的文件夹。取消勾选后，连
  中间层级的容器文件夹也会各自单独渲染一张。
- **输出目录 / 文件名前缀 / 扩展名 / 分辨率 / 采样 / 透明背景**。
- **仅预览（不渲染）**：勾选后只打印将要执行的操作和输出路径，不会真正调用渲染，
  便于先确认文件夹检测结果和文件命名是否符合预期。

点击 **Refresh** 扫描摄像机与文件夹树，点击 **Render All** 执行。渲染每一个
目标文件夹前，会先把扫描到的所有文件夹统一隐藏，再单独点亮该文件夹及其所有
祖先文件夹，从而保证嵌套很深的文件夹也只会让自己这一条分支出现在画面里；
渲染出图后，无论成功还是中途报错，都会把所有文件夹的可见性还原为运行前的
状态。输出文件名由该文件夹在树中的完整路径拼接而成（例如
`Characters_Hero_OutfitA.png`），避免不同分支下同名文件夹互相覆盖。

也可以不使用 UI，直接在 Toolbag 的 Python 控制台调用：

```python
import batch_render_by_folder as brf

targets, all_folders = brf.get_render_targets()  # 或 brf.get_render_targets("某个父文件夹名")
brf.batch_render(
    targets,
    all_folders,
    camera_name="Camera01",
    output_dir="C:/renders",
    prefix="",
    ext=".png",
)
```

## “文件夹”的判定规则

Toolbag 的 Python API 中，场景大纲里的文件夹/分组节点没有专属子类——摄像机
(`CameraObject`)、灯光(`LightObject`)、网格(`MeshObject`) 等都有各自的子类，
文件夹本质上是未被特化的基类 `mset.SceneObject` 实例（官方 API 里用来创建
分组的 `mset.groupObjects(list: List[SceneObject])` 也是把一组 SceneObject
收纳进一个新的 SceneObject 容器，没有专属的 Folder/Group 子类）。因此脚本用
`type(obj) is mset.SceneObject`（精确类型匹配）递归判断某个对象是否为
“文件夹”，文件夹里可以再嵌套任意层级的文件夹。

如果你的场景里存在没有专属子类、但又不属于要渲染的“文件夹”的对象（导致被
误判为文件夹），可以把它的名字加进脚本顶部的 `EXCLUDE_NAMES` 列表中排除。

## 已知限制 / 环境说明

- 官方 Toolbag 5 Python API 参考站点当前对自动化请求返回 403，无法直接抓取
  逐字的官方签名；脚本中用到的接口（`mset.getAllObjects`、`mset.findObject`、
  `SceneObject.visible/parent/getChildren`、`mset.renderCamera` 及
  `UIWindow/UIButton/UITextField/UIListBox/UICheckBox/UILabel` 等 UI 类）
  均通过 Marmoset 官方博客文章、社区脚本示例，以及 PyPI 上 Marmoset 官方发布
  的 `mset` 自动补全库（no-op 版本运行库）交叉核实。
- 如果实际运行时某个 UI 控件的构造参数或方法名与你所用的 Toolbag 5 具体版本
  略有出入，请打开 Toolbag 内置的 `Help > Python API Reference` 核对，按需
  微调 `BatchRenderPanel` 里对应控件的写法；核心渲染逻辑（`get_target_folders`
  / `batch_render`）不依赖 UI，可以脱离面板独立使用。
- 建议先勾选“仅预览（不渲染）”跑一遍，确认检测到的文件夹列表、输出路径命名
  都符合预期后，再正式渲染。
