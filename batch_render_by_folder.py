"""
Marmoset Toolbag 5 - 按文件夹批量渲染插件
==========================================

功能：
    在场景大纲（Scene Objects）中，递归遍历"文件夹"（分组节点）的整棵
    嵌套树，依次让每个文件夹（默认只取"叶子"文件夹，即自身不再包含
    子文件夹的那一级）单独可见、其余全部隐藏，使用指定摄像机逐一渲染，
    并以该文件夹在树中的完整路径命名输出文件，实现批量出图。

典型用途：
    同一个摄像机/灯光/环境搭建好之后，把不同的资产/变体各自放进一个
    文件夹（例如 "Variant_A" / "Variant_B" / "Character_01" ...），
    这些文件夹本身也可以再分层级（比如 "Characters/Hero/OutfitA"），
    运行本插件即可一次性把每个变体单独渲染出图。

安装方式（二选一）：
    1. 放入 Toolbag 的 Plugins 目录（Help > Show Plugins Folder），
       重启 Toolbag 后会在 Plugins 菜单看到本插件，点击即可打开面板。
    2. 打开 Toolbag 顶部 Scripting/Console 面板，通过
       “Load Script” 手动加载本文件运行。

使用方式：
    运行后会弹出一个浮动面板：
        - Camera：从场景中检测到的所有摄像机里选择一个用于渲染
        - Parent Folder（可留空）：留空表示从"场景根目录"开始递归扫描；
          填写某个文件夹名称，则只从该文件夹往下递归扫描
        - Leaf Folders Only：勾选（默认）时只渲染"叶子"文件夹，即自身
          不再包含子文件夹的那一级——这才是真正对应"一个变体"的文件夹；
          取消勾选则连中间层级的容器文件夹也会各自单独渲染一张
        - Output Dir / Prefix / Extension / Width / Height / Sampling / Transparency
        - "Refresh"：重新扫描摄像机和文件夹树，填充列表
        - "Dry Run (Preview Only)"：勾选后只打印将要执行的操作，不会真正渲染
        - "Render All"：执行渲染，渲染结束后会把所有文件夹的可见性
          还原为运行前的状态

    注意：Marmoset Toolbag 的 UI 对中文字符渲染支持不佳（会显示为方块），
    因此面板里的所有文字（标题/标签/按钮/状态提示）均使用英文，
    仅代码注释和本说明使用中文。

关于"文件夹"的识别方式：
    Toolbag 的 Python API 里，场景大纲中的文件夹/分组节点没有专属的
    子类——摄像机(CameraObject)、灯光(LightObject)、网格(MeshObject)
    等都有各自的子类，而文件夹本质上就是一个未被特化的基类
    mset.SceneObject 实例（官方 API 里用来创建分组的
    `mset.groupObjects(list: List[SceneObject])` 也是把一组
    SceneObject 收纳进一个新的 SceneObject 容器）。因此这里用
    `type(obj) is mset.SceneObject`（精确类型匹配，而非 isinstance）
    来判断某个对象是不是"文件夹"，并且是递归判断——文件夹里面还可以
    再嵌套文件夹。如果你的场景中有其它没有专属子类、但也不是文件夹的
    对象导致误判，可以在 EXCLUDE_NAMES 里把它的名字加进去排除掉。

关于文件夹的可见性隔离：
    渲染某个（嵌套很深的）文件夹时，必须保证它本身以及它所有的祖先
    文件夹都可见，同时这棵树里其它所有文件夹（包括其它分支、以及
    该文件夹自己的子文件夹——它们会随父级一起显示，属于预期行为）
    都要隐藏，这样画面里才只会出现这一个变体。脚本里每次渲染前都会
    先把扫描到的所有文件夹统一隐藏，再单独点亮目标文件夹及其祖先链。

如果你不需要 UI，也可以直接在 Toolbag 的 Python 控制台里调用：
    import batch_render_by_folder as brf
    targets, all_folders = brf.get_render_targets()
    brf.batch_render(targets, all_folders, camera_name="Camera01", output_dir="C:/renders")
"""

import os
import mset


# ------------------------- 默认配置（可直接修改） -------------------------

DEFAULT_OUTPUT_DIR = ""        # 留空时，运行时会提示先在面板里填写
DEFAULT_FILE_PREFIX = ""       # 输出文件名前缀，例如 "render_"
DEFAULT_FILE_EXT = ".png"      # 输出格式后缀，Toolbag 按后缀名判断导出格式
DEFAULT_WIDTH = -1             # -1 = 使用 Render 设置里的分辨率
DEFAULT_HEIGHT = -1
DEFAULT_SAMPLING = -1          # -1 = 使用 Render 设置里的采样
DEFAULT_TRANSPARENCY = False
DEFAULT_LEAF_ONLY = True       # True = 只渲染没有子文件夹的"叶子"文件夹
DEFAULT_PATH_SEPARATOR = "_"   # 嵌套路径各级名称之间的连接符，用于生成文件名

# 扫描到"文件夹"时，即使名字符合条件，也要排除掉的对象名（原样字符串匹配）
EXCLUDE_NAMES = []

# ---------------------------------------------------------------------------


def is_folder(obj):
    """判断一个场景对象是否是"文件夹/分组"节点（见文件顶部说明）。"""
    return type(obj) is mset.SceneObject and obj.name not in EXCLUDE_NAMES


def collect_folders(parent_name=""):
    """
    递归遍历文件夹树，返回按深度优先顺序排列的条目列表，每个条目是一个 dict：
        {
            "obj": SceneObject,          # 该文件夹对象本身
            "path": ("A", "A1"),          # 从扫描起点到该文件夹的完整名称路径
            "ancestors": [A_obj, ...],    # 该文件夹的所有祖先文件夹对象（不含自己）
            "is_leaf": bool,               # 是否不再包含任何子文件夹
        }

    parent_name 为空字符串时，从场景根目录开始扫描；否则先用
    mset.findObject 找到该名称的对象，再从它的直接子级开始扫描。
    """
    parent_name = (parent_name or "").strip()

    if parent_name:
        parent = mset.findObject(parent_name)
        if parent is None:
            mset.err("Parent object '{}' not found, scanning scene root instead.".format(parent_name))
            root_children = [o for o in mset.getAllObjects() if o.parent is None]
        else:
            root_children = parent.getChildren()
    else:
        root_children = [o for o in mset.getAllObjects() if o.parent is None]

    entries = []

    def walk(children, path, ancestors):
        folders = sorted([o for o in children if is_folder(o)], key=lambda o: o.name)
        for folder in folders:
            folder_path = path + (folder.name,)
            folder_children = folder.getChildren()
            child_folders = [c for c in folder_children if is_folder(c)]
            entries.append({
                "obj": folder,
                "path": folder_path,
                "ancestors": list(ancestors),
                "is_leaf": len(child_folders) == 0,
            })
            walk(folder_children, folder_path, ancestors + [folder])

    walk(root_children, (), [])
    return entries


def get_render_targets(parent_name="", leaf_only=DEFAULT_LEAF_ONLY):
    """
    返回 (targets, all_folder_objs)：
        targets         -- 要渲染的条目列表（leaf_only=True 时只保留叶子文件夹）
        all_folder_objs -- 扫描到的全部文件夹对象（不论层级），渲染时用来先
                            统一隐藏，再逐个点亮目标及其祖先链
    """
    entries = collect_folders(parent_name)
    all_folder_objs = [entry["obj"] for entry in entries]
    targets = [e for e in entries if e["is_leaf"]] if leaf_only else entries
    return targets, all_folder_objs


def get_all_cameras():
    """获取场景中所有摄像机对象，按名称排序。"""
    cameras = [o for o in mset.getAllObjects() if isinstance(o, mset.CameraObject)]
    cameras.sort(key=lambda o: o.name)
    return cameras


def safe_filename(name):
    """把文件夹名称中操作系统不允许出现在文件名里的字符替换掉。"""
    invalid_chars = '\\/:*?"<>|'
    for ch in invalid_chars:
        name = name.replace(ch, "_")
    return name.strip() or "untitled"


def batch_render(
    targets,
    all_folder_objs,
    camera_name,
    output_dir,
    prefix=DEFAULT_FILE_PREFIX,
    ext=DEFAULT_FILE_EXT,
    width=DEFAULT_WIDTH,
    height=DEFAULT_HEIGHT,
    sampling=DEFAULT_SAMPLING,
    transparency=DEFAULT_TRANSPARENCY,
    path_separator=DEFAULT_PATH_SEPARATOR,
    dry_run=False,
    log=print,
):
    """
    依次渲染 targets 中的每个文件夹条目：先把 all_folder_objs 里的所有
    文件夹隐藏，再点亮该条目自身及其祖先链，用指定摄像机渲染，并以该
    条目的完整名称路径命名输出文件。渲染结束后（或出错时）会把
    all_folder_objs 的可见性还原为调用前的状态。
    """
    if not targets:
        log("No folders found to render. Check scene structure or parent folder name.")
        return []

    if not camera_name:
        log("No camera specified. Render cancelled.")
        return []

    if not output_dir:
        log("No output directory specified. Render cancelled.")
        return []

    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)

    # 记录渲染前的可见性，结束后还原
    original_visibility = {folder.uid: folder.visible for folder in all_folder_objs}

    output_paths = []
    try:
        for index, target in enumerate(targets):
            for folder in all_folder_objs:
                folder.visible = False
            for ancestor in target["ancestors"]:
                ancestor.visible = True
            target["obj"].visible = True

            filename = safe_filename(prefix + path_separator.join(target["path"])) + ext
            out_path = os.path.join(output_dir, filename)
            output_paths.append(out_path)

            log("[{}/{}] Rendering '{}' -> {}".format(
                index + 1, len(targets), "/".join(target["path"]), out_path))

            if not dry_run:
                mset.renderCamera(
                    path=out_path,
                    width=width,
                    height=height,
                    sampling=sampling,
                    transparency=transparency,
                    camera=camera_name,
                )

        log("Done. Processed {} folder(s).".format(len(targets)))
    finally:
        for folder in all_folder_objs:
            if folder.uid in original_visibility:
                folder.visible = original_visibility[folder.uid]

    return output_paths


# --------------------------------- UI ---------------------------------
# 所有 UI 文字使用英文：Marmoset Toolbag 对中文字符渲染支持不佳（会显示方块）。


class BatchRenderPanel:
    def __init__(self):
        self.cameras = []
        self.targets = []
        self.all_folder_objs = []

        self.window = mset.UIWindow("Batch Render By Folder")

        self.camera_list = mset.UIListBox()
        self.camera_list.title = "Camera"

        self.parent_field = mset.UITextField()

        self.leaf_only_check = mset.UICheckBox()
        self.leaf_only_check.label = "Leaf Folders Only"
        self.leaf_only_check.value = DEFAULT_LEAF_ONLY

        self.output_field = mset.UITextField()
        self.output_field.value = DEFAULT_OUTPUT_DIR

        self.prefix_field = mset.UITextField()
        self.prefix_field.value = DEFAULT_FILE_PREFIX

        self.ext_field = mset.UITextField()
        self.ext_field.value = DEFAULT_FILE_EXT

        self.width_field = mset.UITextFieldInt()
        self.width_field.value = DEFAULT_WIDTH

        self.height_field = mset.UITextFieldInt()
        self.height_field.value = DEFAULT_HEIGHT

        self.sampling_field = mset.UITextFieldInt()
        self.sampling_field.value = DEFAULT_SAMPLING

        self.transparency_check = mset.UICheckBox()
        self.transparency_check.label = "Transparent Background"
        self.transparency_check.value = DEFAULT_TRANSPARENCY

        self.dry_run_check = mset.UICheckBox()
        self.dry_run_check.label = "Dry Run (Preview Only)"
        self.dry_run_check.value = False

        self.folder_list = mset.UIListBox()
        self.folder_list.title = "Detected Folders (will be rendered)"

        self.status_label = mset.UILabel()
        self.status_label.text = "Ready. Click Refresh to start."

        self.refresh_button = mset.UIButton("Refresh")
        self.refresh_button.onClick = self.refresh

        self.render_button = mset.UIButton("Render All")
        self.render_button.onClick = self.run_render

        self._build_layout()
        self.refresh()

    def _build_layout(self):
        w = self.window
        w.clearElements()

        w.addElement(self.camera_list)
        w.addReturn()

        parent_label = mset.UILabel()
        parent_label.text = "Parent Folder (blank = scene root):"
        w.addElement(parent_label)
        w.addElement(self.parent_field)
        w.addReturn()

        w.addElement(self.leaf_only_check)
        w.addReturn()

        output_label = mset.UILabel()
        output_label.text = "Output Dir:"
        w.addElement(output_label)
        w.addElement(self.output_field)
        w.addReturn()

        prefix_label = mset.UILabel()
        prefix_label.text = "Filename Prefix:"
        w.addElement(prefix_label)
        w.addElement(self.prefix_field)
        w.addReturn()

        ext_label = mset.UILabel()
        ext_label.text = "Extension:"
        w.addElement(ext_label)
        w.addElement(self.ext_field)
        w.addReturn()

        width_label = mset.UILabel()
        width_label.text = "Width (-1 = default):"
        w.addElement(width_label)
        w.addElement(self.width_field)
        w.addReturn()

        height_label = mset.UILabel()
        height_label.text = "Height (-1 = default):"
        w.addElement(height_label)
        w.addElement(self.height_field)
        w.addReturn()

        sampling_label = mset.UILabel()
        sampling_label.text = "Sampling (-1 = default):"
        w.addElement(sampling_label)
        w.addElement(self.sampling_field)
        w.addReturn()

        w.addElement(self.transparency_check)
        w.addReturn()
        w.addElement(self.dry_run_check)
        w.addReturn()

        w.addElement(self.folder_list)
        w.addReturn()

        w.addElement(self.refresh_button)
        w.addElement(self.render_button)
        w.addReturn()

        w.addElement(self.status_label)

    def _set_status(self, text):
        self.status_label.text = text
        print(text)

    def refresh(self):
        self.cameras = get_all_cameras()
        self.camera_list.clearItems()
        for cam in self.cameras:
            self.camera_list.addItem(cam.name)
        if self.cameras:
            self.camera_list.selectedItem = 0

        self.targets, self.all_folder_objs = get_render_targets(
            self.parent_field.value, self.leaf_only_check.value)
        self.folder_list.clearItems()
        for target in self.targets:
            self.folder_list.addItem("/".join(target["path"]))

        self._set_status(
            "Found {} camera(s), {} folder(s) ({} total incl. non-leaf).".format(
                len(self.cameras), len(self.targets), len(self.all_folder_objs))
        )

    def run_render(self):
        if not self.cameras:
            self._set_status("No cameras found in scene. Cannot render.")
            return

        cam_index = self.camera_list.selectedItem
        if cam_index is None or cam_index < 0 or cam_index >= len(self.cameras):
            self._set_status("Please select a camera from the list.")
            return
        camera_name = self.cameras[cam_index].name

        targets, all_folder_objs = get_render_targets(
            self.parent_field.value, self.leaf_only_check.value)
        if not targets:
            self._set_status("No folders found to render.")
            return

        output_dir = self.output_field.value.strip()
        if not output_dir:
            self._set_status("Please enter an output directory.")
            return

        self._set_status("Rendering...")
        batch_render(
            targets=targets,
            all_folder_objs=all_folder_objs,
            camera_name=camera_name,
            output_dir=output_dir,
            prefix=self.prefix_field.value,
            ext=self.ext_field.value or DEFAULT_FILE_EXT,
            width=self.width_field.value,
            height=self.height_field.value,
            sampling=self.sampling_field.value,
            transparency=self.transparency_check.value,
            dry_run=self.dry_run_check.value,
            log=self._set_status,
        )


_panel = BatchRenderPanel()
_panel.window.visible = True
