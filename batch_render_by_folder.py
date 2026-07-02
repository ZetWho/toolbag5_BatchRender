"""
Marmoset Toolbag 5 - 按文件夹批量渲染插件
==========================================

功能：
    在场景大纲（Scene Objects）中，依次显示每一个"文件夹"（分组节点），
    同时隐藏其余文件夹，使用指定摄像机逐一渲染，并以文件夹名称作为
    输出文件名，实现"一个文件夹 = 一张渲染图"的批量出图流程。

典型用途：
    同一个摄像机/灯光/环境搭建好之后，把不同的资产/变体各自放进一个
    文件夹（例如 "Variant_A" / "Variant_B" / "Character_01" ...），
    运行本插件即可一次性把每个变体单独渲染出图。

安装方式（二选一）：
    1. 放入 Toolbag 的 Plugins 目录（Help > Show Plugins Folder），
       重启 Toolbag 后会在 Plugins 菜单看到本插件，点击即可打开面板。
    2. 打开 Toolbag 顶部 Scripting/Console 面板，通过
       “Load Script” 手动加载本文件运行。

使用方式：
    运行后会弹出一个浮动面板：
        - 摄像机：从场景中检测到的所有摄像机里选择一个用于渲染
        - 父级文件夹（可留空）：留空表示扫描"场景根目录"下的所有顶层
          文件夹；填写某个文件夹名称，则只遍历该文件夹下的子文件夹
          （用于场景本身也用文件夹分了层级的情况）
        - 输出目录 / 文件名前缀 / 扩展名 / 分辨率 / 采样 / 透明通道
        - "刷新列表"：重新扫描摄像机和文件夹，填充下拉列表
        - "仅预览（不渲染）"：勾选后只打印将要执行的操作，不会真正渲染
        - "开始批量渲染"：执行渲染，渲染结束后会把所有文件夹的可见性
          还原为运行前的状态

关于"文件夹"的识别方式：
    Toolbag 的 Python API 里，场景大纲中的文件夹/分组节点没有专属的
    子类——摄像机(CameraObject)、灯光(LightObject)、网格(MeshObject)
    等都有各自的子类，而文件夹本质上就是一个未被特化的基类
    mset.SceneObject 实例。因此这里用 `type(obj) is mset.SceneObject`
    （精确类型匹配，而非 isinstance）来判断某个对象是不是"文件夹"。
    如果你的场景中有其它没有专属子类、但也不是文件夹的对象导致误判，
    可以在 EXCLUDE_NAMES 里把它的名字加进去排除掉。

如果你不需要 UI，也可以直接在 Toolbag 的 Python 控制台里调用：
    import batch_render_by_folder as brf
    folders = brf.get_target_folders()
    brf.batch_render(folders, camera_name="Camera01", output_dir="C:/renders")
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

# 扫描到"文件夹"时，即使名字符合条件，也要排除掉的对象名（原样字符串匹配）
EXCLUDE_NAMES = []

# ---------------------------------------------------------------------------


def is_folder(obj):
    """判断一个场景对象是否是"文件夹/分组"节点（见文件顶部说明）。"""
    return type(obj) is mset.SceneObject and obj.name not in EXCLUDE_NAMES


def get_target_folders(parent_name=""):
    """
    获取要批量渲染的文件夹列表，按名称排序。

    parent_name 为空字符串时，扫描场景根目录下的所有顶层文件夹；
    否则先用 mset.findObject 找到该名称的对象，再扫描它的直接子文件夹。
    """
    parent_name = (parent_name or "").strip()

    if parent_name:
        parent = mset.findObject(parent_name)
        if parent is None:
            mset.err("找不到名为 '{}' 的父级对象，改为扫描场景根目录。".format(parent_name))
            candidates = [o for o in mset.getAllObjects() if o.parent is None]
        else:
            candidates = parent.getChildren()
    else:
        candidates = [o for o in mset.getAllObjects() if o.parent is None]

    folders = [o for o in candidates if is_folder(o)]
    folders.sort(key=lambda o: o.name)
    return folders


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
    folders,
    camera_name,
    output_dir,
    prefix=DEFAULT_FILE_PREFIX,
    ext=DEFAULT_FILE_EXT,
    width=DEFAULT_WIDTH,
    height=DEFAULT_HEIGHT,
    sampling=DEFAULT_SAMPLING,
    transparency=DEFAULT_TRANSPARENCY,
    dry_run=False,
    log=print,
):
    """
    依次显示每个文件夹（同时隐藏其余文件夹），用指定摄像机渲染，
    并以文件夹名称命名输出文件。渲染结束后（或出错时）会把所有
    文件夹的可见性还原为调用前的状态。
    """
    if not folders:
        log("没有检测到可渲染的文件夹，请检查场景结构或父级文件夹名称。")
        return []

    if not camera_name:
        log("未指定摄像机，已取消渲染。")
        return []

    if not output_dir:
        log("未指定输出目录，已取消渲染。")
        return []

    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)

    # 记录渲染前的可见性，结束后还原
    original_visibility = {folder.uid: folder.visible for folder in folders}

    output_paths = []
    try:
        for index, folder in enumerate(folders):
            for other in folders:
                other.visible = (other is folder)

            filename = safe_filename(prefix + folder.name) + ext
            out_path = os.path.join(output_dir, filename)
            output_paths.append(out_path)

            log("[{}/{}] 渲染文件夹 '{}' -> {}".format(
                index + 1, len(folders), folder.name, out_path))

            if not dry_run:
                mset.renderCamera(
                    path=out_path,
                    width=width,
                    height=height,
                    sampling=sampling,
                    transparency=transparency,
                    camera=camera_name,
                )

        log("完成，共处理 {} 个文件夹。".format(len(folders)))
    finally:
        for folder in folders:
            if folder.uid in original_visibility:
                folder.visible = original_visibility[folder.uid]

    return output_paths


# --------------------------------- UI ---------------------------------


class BatchRenderPanel:
    def __init__(self):
        self.cameras = []
        self.folders = []

        self.window = mset.UIWindow("按文件夹批量渲染")

        self.camera_list = mset.UIListBox()
        self.camera_list.title = "摄像机"

        self.parent_field = mset.UITextField()

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
        self.transparency_check.label = "透明背景"
        self.transparency_check.value = DEFAULT_TRANSPARENCY

        self.dry_run_check = mset.UICheckBox()
        self.dry_run_check.label = "仅预览（不渲染）"
        self.dry_run_check.value = False

        self.folder_list = mset.UIListBox()
        self.folder_list.title = "检测到的文件夹（将全部渲染）"

        self.status_label = mset.UILabel()
        self.status_label.text = "就绪，点击“刷新列表”开始。"

        self.refresh_button = mset.UIButton("刷新列表")
        self.refresh_button.onClick = self.refresh

        self.render_button = mset.UIButton("开始批量渲染")
        self.render_button.onClick = self.run_render

        self._build_layout()
        self.refresh()

    def _build_layout(self):
        w = self.window
        w.clearElements()

        w.addElement(mset.UILabel())
        w.addElement(self.camera_list)
        w.addReturn()

        parent_label = mset.UILabel()
        parent_label.text = "父级文件夹（留空=场景根目录）:"
        w.addElement(parent_label)
        w.addElement(self.parent_field)
        w.addReturn()

        output_label = mset.UILabel()
        output_label.text = "输出目录:"
        w.addElement(output_label)
        w.addElement(self.output_field)
        w.addReturn()

        prefix_label = mset.UILabel()
        prefix_label.text = "文件名前缀:"
        w.addElement(prefix_label)
        w.addElement(self.prefix_field)
        w.addReturn()

        ext_label = mset.UILabel()
        ext_label.text = "扩展名:"
        w.addElement(ext_label)
        w.addElement(self.ext_field)
        w.addReturn()

        width_label = mset.UILabel()
        width_label.text = "宽度(-1=默认):"
        w.addElement(width_label)
        w.addElement(self.width_field)
        w.addReturn()

        height_label = mset.UILabel()
        height_label.text = "高度(-1=默认):"
        w.addElement(height_label)
        w.addElement(self.height_field)
        w.addReturn()

        sampling_label = mset.UILabel()
        sampling_label.text = "采样(-1=默认):"
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

        self.folders = get_target_folders(self.parent_field.value)
        self.folder_list.clearItems()
        for folder in self.folders:
            self.folder_list.addItem(folder.name)

        self._set_status(
            "检测到 {} 个摄像机，{} 个文件夹。".format(
                len(self.cameras), len(self.folders))
        )

    def run_render(self):
        if not self.cameras:
            self._set_status("场景中没有摄像机，无法渲染。")
            return

        cam_index = self.camera_list.selectedItem
        if cam_index is None or cam_index < 0 or cam_index >= len(self.cameras):
            self._set_status("请先在列表中选择一个摄像机。")
            return
        camera_name = self.cameras[cam_index].name

        folders = get_target_folders(self.parent_field.value)
        if not folders:
            self._set_status("没有检测到可渲染的文件夹。")
            return

        output_dir = self.output_field.value.strip()
        if not output_dir:
            self._set_status("请先填写输出目录。")
            return

        self._set_status("开始渲染...")
        batch_render(
            folders=folders,
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
