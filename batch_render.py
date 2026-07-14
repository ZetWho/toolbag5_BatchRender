"""
Batch Renderer Pro -- Marmoset Toolbag 5 Current-Scene Folder Batch Renderer

Workflow:
- Use the current opened .tbscene only; do not load multiple scenes.
- Choose one camera by name, or use the active viewport camera.
- Discover display folders/groups below the Toolbag "Scene" root.
- Render selected folders one by one by hiding the other selected folders.
- Save each image with the folder name, e.g. Output/FolderName.png.

Installation:
Place this file in:
C:/Users/<user>/AppData/Local/Marmoset Toolbag 5/plugins/
Launch via the Plugins menu in Toolbag.
"""
import mset
import os
import re
import time


# -- Configuration --
class Config:
    def __init__(self):
        self.output_dir = ""
        self.width = 1920
        self.height = 1080
        self.format = "PNG"       # JPEG, PNG, TGA, PSD, EXR
        self.samples = 256
        self.transparency = False
        self.camera_name = ""      # empty = active camera
        self.use_subcam = False     # render each folder with a camera found inside it
        self.viewport_pass = ""    # empty = final/composite viewport pass
        self.root_only = True       # True = direct children under Toolbag Scene root
        self.overwrite = True
        self.folder_enabled = {}    # uid -> bool
        # Exact type names shown in the folder list. Exact matching matters:
        # CameraObject/LightObject/MeshObject all inherit TransformObject, so
        # an isinstance check would let cameras and lights into the list.
        self.type_filter = {
            "TransformObject": True,   # Toolbag group/folder nodes
            "SceneObject": False,      # bare outliner containers
            "MeshObject": False,       # individual meshes
        }


config = Config()
window = None


# -- Logging --
def log(msg):
    ts = time.strftime("%H:%M:%S")
    mset.log("[{}] [BatchRendererPro] {}".format(ts, msg))


def err(msg):
    ts = time.strftime("%H:%M:%S")
    mset.err("[{}] [BatchRendererPro] {}".format(ts, msg))


# -- Safe API Helpers --
def type_name(obj):
    try:
        return obj.__class__.__name__
    except Exception:
        return "UnknownType"


def is_mset_type(obj, type_name_value):
    cls = getattr(mset, type_name_value, None)
    return cls is not None and isinstance(obj, cls)


def safe_name(name):
    if name is None:
        return "Unnamed"
    name = str(name).strip()
    if not name:
        return "Unnamed"
    return name


def get_obj_name(obj):
    try:
        return safe_name(obj.name)
    except Exception:
        return "Unnamed"


def get_obj_uid(obj):
    try:
        return obj.uid
    except Exception:
        return id(obj)


def get_parent(obj):
    try:
        return obj.parent
    except Exception:
        return None


def get_children(obj):
    try:
        children = obj.getChildren()
        if children is None:
            return []
        return list(children)
    except Exception:
        return []


def has_children(obj):
    return len(get_children(obj)) > 0


def is_root_object(obj):
    return get_parent(obj) is None


def is_scene_root(obj):
    """Toolbag outliner root named Scene. It is a container, not a render folder."""
    return is_root_object(obj) and get_obj_name(obj).lower() == "scene"


def enabled_filter_types():
    return [t for t, enabled in config.type_filter.items() if enabled]


def object_depth(obj):
    depth = 0
    parent = get_parent(obj)
    safety = 0
    while parent is not None and safety < 128:
        depth += 1
        parent = get_parent(parent)
        safety += 1
    return depth


def find_scene_root():
    all_objs = mset.getAllObjects()

    # Preferred: exact Toolbag outliner root from the screenshot.
    for obj in all_objs:
        if is_scene_root(obj):
            return obj

    # Fallback: root object with the most children.
    root_candidates = [obj for obj in all_objs if is_root_object(obj) and has_children(obj)]
    if root_candidates:
        root_candidates.sort(key=lambda o: len(get_children(o)), reverse=True)
        return root_candidates[0]

    return None


def collect_descendants(obj):
    results = []
    stack = list(get_children(obj))
    while stack:
        current = stack.pop(0)
        results.append(current)
        stack[0:0] = get_children(current)
    return results


def is_render_folder_candidate(obj):
    if obj is None:
        return False
    if is_scene_root(obj):
        return False
    # Exact type-name allowlist driven by the UI type filter. Every other
    # type (cameras, lights, sky, render object, submeshes, ...) is excluded
    # automatically because its exact class name is never in the filter.
    if type_name(obj) not in enabled_filter_types():
        return False
    # Name fallback for display-only items that surface as an allowed type.
    if get_obj_name(obj).lower() in ["main camera", "camera", "sky", "render", "renders"]:
        return False
    # Do not require children here. Toolbag folder-like outliner nodes may not
    # expose their descendants through getAllObjects() the same way transforms do.
    return True


def get_folder_candidates():
    """Return Toolbag outliner folder/group-like objects from the current scene.

    Important Toolbag 5 behavior from the user's screenshot:
    The yellow folders r_frame01... are direct children of the outliner root
    named "Scene". They are not parent=None roots, so checking only parent is
    None incorrectly returns only the Scene container.
    """
    scene_root = find_scene_root()

    if scene_root is not None:
        if config.root_only:
            candidates = get_children(scene_root)
        else:
            candidates = collect_descendants(scene_root)
    else:
        candidates = mset.getAllObjects()

    folders = []
    seen = set()
    for obj in candidates:
        uid = get_obj_uid(obj)
        if uid in seen:
            continue
        seen.add(uid)
        if is_render_folder_candidate(obj):
            folders.append(obj)

    # Fallback for scenes where getChildren() is sparse but getAllObjects() has parents.
    if not folders:
        for obj in mset.getAllObjects():
            uid = get_obj_uid(obj)
            if uid in seen:
                continue
            seen.add(uid)
            if is_render_folder_candidate(obj):
                folders.append(obj)

    folders.sort(key=lambda o: get_obj_name(o).lower())
    return folders


def get_cameras():
    cameras = []
    for obj in mset.getAllObjects():
        if is_mset_type(obj, "CameraObject"):
            cameras.append(obj)
    cameras.sort(key=lambda o: get_obj_name(o).lower())
    return cameras


def find_camera():
    """Find the configured camera, or fall back to the active camera."""
    name = config.camera_name.strip()

    if name:
        cameras = get_cameras()
        for cam in cameras:
            if cam.name == name:
                return cam
        for cam in cameras:
            if cam.name.lower() == name.lower():
                return cam
        for cam in cameras:
            if name.lower() in cam.name.lower():
                return cam
        return None

    try:
        return mset.getCamera()
    except Exception:
        return None


def find_folder_camera(folder):
    """First CameraObject (by name) among the folder's descendants, or None."""
    cams = [o for o in collect_descendants(folder) if is_mset_type(o, "CameraObject")]
    if not cams:
        return None
    cams.sort(key=lambda o: get_obj_name(o).lower())
    return cams[0]


def sanitize_filename(name):
    name = safe_name(name)
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")
    if not name:
        name = "Unnamed"
    return name


def format_extension(fmt):
    fmt = fmt.strip().upper()
    if fmt == "JPEG":
        return "jpg"
    return fmt.lower()


def unique_output_path(base_dir, base_name, ext, used_names):
    safe_base = sanitize_filename(base_name)
    key = safe_base.lower()
    count = used_names.get(key, 0) + 1
    used_names[key] = count

    if count == 1:
        file_name = "{}.{}".format(safe_base, ext)
    else:
        file_name = "{}_{:02d}.{}".format(safe_base, count, ext)

    path = os.path.join(base_dir, file_name)

    if config.overwrite:
        return path

    index = 2
    while os.path.exists(path):
        file_name = "{}_{:02d}.{}".format(safe_base, index, ext)
        path = os.path.join(base_dir, file_name)
        index += 1
    return path


def ensure_output_dir():
    if not config.output_dir:
        err("Output directory is not set.")
        return False
    try:
        if not os.path.isdir(config.output_dir):
            os.makedirs(config.output_dir)
        return True
    except Exception as e:
        err("Cannot create output directory: {}".format(e))
        return False


def apply_camera(camera):
    try:
        mset.setCamera(camera)
    except Exception:
        pass


def describe_object(obj):
    parent = get_parent(obj)
    parent_name = get_obj_name(parent) if parent is not None else "None"
    try:
        visible = obj.visible
    except Exception:
        visible = "?"
    return "name='{}' type={} uid={} parent='{}' depth={} visible={}".format(
        get_obj_name(obj), type_name(obj), get_obj_uid(obj), parent_name, object_depth(obj), visible)


def log_scene_tree():
    scene_root = find_scene_root()
    log("=== Scene Tree Debug Start ===")
    if scene_root is None:
        log("Scene root not found. Dumping mset.getAllObjects().")
        for obj in mset.getAllObjects():
            log(describe_object(obj))
    else:
        log("Scene root: {}".format(describe_object(scene_root)))

        def walk(obj, depth):
            prefix = "  " * depth
            log("{}- {}".format(prefix, describe_object(obj)))
            for child in get_children(obj):
                walk(child, depth + 1)

        walk(scene_root, 0)
    log("Folder candidates: {}".format(len(get_folder_candidates())))
    for folder in get_folder_candidates():
        log("Candidate: {}".format(describe_object(folder)))
    log("=== Scene Tree Debug End ===")


# -- Rendering --
def render_single_folder(folder, camera, output_path):
    """Render one folder with explicit output filename."""
    apply_camera(camera)
    log("Rendering folder '{}' -> {}".format(get_obj_name(folder), output_path))

    # Explicit file path is the key difference from RenderObject.renderImages();
    # it lets us use the folder name as the image filename.
    mset.renderCamera(
        output_path,
        config.width,
        config.height,
        config.samples,
        config.transparency,
        camera.name,
        config.viewport_pass
    )


def batch_render_current_scene():
    if not ensure_output_dir():
        return

    # With Use Sub-Cam the global camera is only a fallback for folders that
    # contain no camera of their own, so a missing global camera is not fatal.
    camera = find_camera()
    if camera is None:
        if config.use_subcam:
            log("No global fallback camera; folders without their own camera will be skipped.")
        elif config.camera_name.strip():
            err("Camera not found: {}".format(config.camera_name.strip()))
            return
        else:
            err("No active camera found. Please enter a camera name or focus a viewport camera.")
            return

    folders = get_folder_candidates()
    selected_folders = [f for f in folders if config.folder_enabled.get(get_obj_uid(f), True)]

    if not selected_folders:
        err("No enabled folders to render. Click Refresh Folders and enable at least one folder.")
        return

    ext = format_extension(config.format)
    used_names = {}

    # Track every object whose visibility we touch (uid -> (obj, original state)),
    # so unchecked folders and ancestor chains are restored too.
    original_visibility = {}

    def set_visible(obj, value):
        uid = get_obj_uid(obj)
        if uid not in original_visibility:
            try:
                original_visibility[uid] = (obj, obj.visible)
            except Exception:
                return
        try:
            obj.visible = value
        except Exception:
            pass

    camera_desc = "Per-Folder Sub-Cam (fallback: {})".format(
        camera.name if camera is not None else "none") if config.use_subcam else camera.name
    log("=== Folder Batch Render Start | Camera: {} | Folders: {} ===".format(camera_desc, len(selected_folders)))
    log("Output: {} | {}x{} | {} | Samples: {}".format(
        config.output_dir, config.width, config.height, config.format, config.samples))

    success_count = 0
    fail_count = 0

    try:
        for index, folder in enumerate(selected_folders, 1):
            log("--- [{}/{}] {} ---".format(index, len(selected_folders), get_obj_name(folder)))

            # Hide ALL candidate folders (checked and unchecked), so folders the
            # user deselected never leak into any rendered image.
            for other in folders:
                set_visible(other, False)

            # Show the current folder plus its ancestor chain: a hidden parent
            # hides its children in Toolbag, so nested folders would otherwise
            # render empty after the hide-all pass above.
            current = folder
            safety = 0
            while current is not None and not is_scene_root(current) and safety < 128:
                set_visible(current, True)
                current = get_parent(current)
                safety += 1

            # Resolve the camera for this folder: its own sub-camera when
            # Use Sub-Cam is enabled, otherwise the global camera.
            folder_camera = camera
            if config.use_subcam:
                subcam = find_folder_camera(folder)
                if subcam is not None:
                    folder_camera = subcam
                    log("Sub-cam: '{}'".format(get_obj_name(subcam)))
                elif camera is not None:
                    log("No camera inside '{}', using fallback '{}'.".format(
                        get_obj_name(folder), camera.name))
                else:
                    fail_count += 1
                    err("SKIP: {} | no camera inside folder and no fallback camera".format(
                        get_obj_name(folder)))
                    continue

            output_path = unique_output_path(config.output_dir, get_obj_name(folder), ext, used_names)

            try:
                render_single_folder(folder, folder_camera, output_path)
                success_count += 1
                log("OK: {}".format(output_path))
            except Exception as e:
                fail_count += 1
                err("FAIL: {} | {}".format(get_obj_name(folder), e))

    finally:
        # Restore every object we touched (selected, unchecked, and ancestors),
        # even if a render fails.
        for uid, (obj, was_visible) in original_visibility.items():
            try:
                obj.visible = was_visible
            except Exception:
                pass
        try:
            mset.freeUnusedResources()
        except Exception:
            pass

    log("=== Folder Batch Render Complete | Success: {} | Failed: {} ===".format(success_count, fail_count))


# -- UI --
def build_ui():
    global window

    if window is None:
        window = mset.UIWindow("Batch Renderer Pro")
        window.visible = True
        window.width = 560
        window.height = 760
    else:
        window.clearElements()

    title = mset.UILabel("Batch Renderer Pro - Current Scene Folders")
    window.addElement(title)
    window.addReturn()

    scene_root = find_scene_root()
    root_text = "Scene Root: {}".format(get_obj_name(scene_root) if scene_root is not None else "Not Found")
    window.addElement(mset.UILabel(root_text))
    window.addReturn()
    window.addReturn()

    # Output Directory
    window.addElement(mset.UILabel("Output Directory:"))
    dir_field = mset.UITextField()
    dir_field.value = config.output_dir
    dir_field.width = 330
    window.addElement(dir_field)

    def pick_output_dir():
        path = mset.showOpenFolderDialog()
        if path:
            config.output_dir = path
            build_ui()

    browse_btn = mset.UIButton("Browse...")
    browse_btn.onClick = pick_output_dir
    window.addElement(browse_btn)
    window.addReturn()
    window.addReturn()

    # Camera
    window.addElement(mset.UILabel("Camera Name:"))
    camera_field = mset.UITextField()
    camera_field.value = config.camera_name
    camera_field.width = 260
    window.addElement(camera_field)

    def use_active_camera():
        cam = None
        try:
            cam = mset.getCamera()
        except Exception:
            cam = None
        if cam is not None:
            config.camera_name = cam.name
            build_ui()
        else:
            err("No active camera found.")

    active_btn = mset.UIButton("Use Active")
    active_btn.onClick = use_active_camera
    window.addElement(active_btn)
    window.addSpace(12)

    # Render each folder with the camera found inside that folder; the
    # camera name above then only serves as a fallback.
    subcam_cb = mset.UICheckBox()
    subcam_cb.value = config.use_subcam

    def toggle_subcam():
        config.use_subcam = subcam_cb.value

    subcam_cb.onChange = toggle_subcam
    window.addElement(subcam_cb)
    window.addElement(mset.UILabel("Use Sub-Cam (camera inside each folder)"))
    window.addReturn()

    cameras = get_cameras()
    if cameras:
        # Collapsible camera list. Like UIScrollBox, UIDrawer's
        # containedControl must be ASSIGNED a full UIWindow; fall back to a
        # flat list if UIDrawer is unavailable.
        camera_area = window
        drawer = None
        try:
            drawer = mset.UIDrawer()
            drawer.title = "Scene Cameras ({})".format(len(cameras))
            drawer.open = False
            drawer_window = mset.UIWindow("Scene Cameras")
            drawer.containedControl = drawer_window
            camera_area = drawer_window
        except Exception:
            drawer = None
            camera_area = window
            window.addElement(mset.UILabel("Scene Cameras:"))
            window.addReturn()

        for cam in cameras:
            def make_use_camera(c):
                def use_camera():
                    config.camera_name = c.name
                    build_ui()
                return use_camera

            cam_btn = mset.UIButton("Use")
            cam_btn.onClick = make_use_camera(cam)
            camera_area.addElement(cam_btn)
            cam_label = mset.UILabel(cam.name)
            camera_area.addElement(cam_label)
            camera_area.addReturn()

        if drawer is not None:
            window.addElement(drawer)
            window.addReturn()
    else:
        window.addElement(mset.UILabel("No CameraObject found. Active viewport camera can still be used."))
        window.addReturn()

    window.addReturn()

    # Render Parameters
    window.addElement(mset.UILabel("Render Settings:"))
    window.addReturn()

    window.addElement(mset.UILabel("Width:"))
    w_field = mset.UITextFieldInt()
    w_field.value = config.width
    w_field.width = 90
    window.addElement(w_field)
    window.addSpace(18)

    window.addElement(mset.UILabel("Height:"))
    h_field = mset.UITextFieldInt()
    h_field.value = config.height
    h_field.width = 90
    window.addElement(h_field)
    window.addReturn()

    window.addElement(mset.UILabel("Format:"))
    fmt_field = mset.UITextField()
    fmt_field.value = config.format
    fmt_field.width = 90
    window.addElement(fmt_field)
    window.addSpace(10)
    window.addElement(mset.UILabel("PNG, JPEG, TGA, PSD, EXR"))
    window.addReturn()

    window.addElement(mset.UILabel("Samples:"))
    samples_field = mset.UITextFieldInt()
    samples_field.value = config.samples
    samples_field.width = 90
    window.addElement(samples_field)
    window.addReturn()

    window.addElement(mset.UILabel("Viewport Pass:"))
    pass_field = mset.UITextField()
    pass_field.value = config.viewport_pass
    pass_field.width = 130
    window.addElement(pass_field)
    window.addSpace(10)
    window.addElement(mset.UILabel("empty = final"))
    window.addReturn()

    transparency_cb = mset.UICheckBox()
    transparency_cb.value = config.transparency
    window.addElement(transparency_cb)
    window.addElement(mset.UILabel("Transparent Background"))
    window.addSpace(20)

    overwrite_cb = mset.UICheckBox()
    overwrite_cb.value = config.overwrite
    window.addElement(overwrite_cb)
    window.addElement(mset.UILabel("Overwrite Existing"))
    window.addReturn()

    root_only_cb = mset.UICheckBox()
    root_only_cb.value = config.root_only
    window.addElement(root_only_cb)
    window.addElement(mset.UILabel("Direct Children Under Scene Only"))
    window.addReturn()
    window.addReturn()

    # Read settings from UI fields
    def read_ui_settings():
        try:
            w = int(w_field.value)
            h = int(h_field.value)
            if w <= 0 or h <= 0:
                err("Width and Height must be positive integers.")
                return False
            config.width = w
            config.height = h
        except (ValueError, TypeError):
            err("Invalid width or height value.")
            return False

        try:
            s = int(samples_field.value)
            if s <= 0:
                err("Samples must be a positive integer.")
                return False
            config.samples = s
        except (ValueError, TypeError):
            err("Invalid samples value.")
            return False

        fmt = fmt_field.value.strip().upper()
        if fmt not in ["PNG", "JPEG", "TGA", "PSD", "EXR"]:
            err("Unsupported format: {}. Use PNG, JPEG, TGA, PSD, or EXR.".format(fmt))
            return False
        config.format = fmt

        out_dir = dir_field.value.strip()
        if not out_dir:
            err("Output directory cannot be empty.")
            return False
        config.output_dir = out_dir

        config.camera_name = camera_field.value.strip()
        config.use_subcam = subcam_cb.value
        config.viewport_pass = pass_field.value.strip()
        config.transparency = transparency_cb.value
        config.overwrite = overwrite_cb.value
        config.root_only = root_only_cb.value
        return True

    def refresh_folders():
        read_ui_settings()
        build_ui()

    refresh_btn = mset.UIButton("Refresh Folders")
    refresh_btn.onClick = refresh_folders
    window.addElement(refresh_btn)

    debug_btn = mset.UIButton("Log Scene Tree")
    debug_btn.onClick = log_scene_tree
    window.addElement(debug_btn)
    window.addReturn()
    window.addReturn()

    # Type filter for the folder list
    window.addElement(mset.UILabel("List Filter:"))

    def make_filter_toggle(type_key, checkbox):
        def toggle():
            config.type_filter[type_key] = checkbox.value
            build_ui()
        return toggle

    for type_key in ["TransformObject", "SceneObject", "MeshObject"]:
        filter_cb = mset.UICheckBox()
        filter_cb.value = config.type_filter.get(type_key, False)
        filter_cb.onChange = make_filter_toggle(type_key, filter_cb)
        window.addElement(filter_cb)
        window.addElement(mset.UILabel(type_key))
        window.addSpace(12)
    window.addReturn()

    # Folder List
    folders = get_folder_candidates()
    window.addElement(mset.UILabel("Folders To Render: {}".format(len(folders))))
    window.addReturn()

    # Put the folder checkboxes inside a UIScrollBox so long lists scroll
    # instead of stretching the panel. containedControl must be ASSIGNED a
    # full UIWindow (reading it yields nothing usable):
    #   scrollbox = mset.UIScrollBox()
    #   scrollbox.containedControl = mset.UIWindow(...)
    # Fall back to the main window if UIScrollBox is unavailable.
    scroll_box = None
    folder_area = window
    try:
        scroll_box = mset.UIScrollBox()
        scroll_window = mset.UIWindow("Folders")
        scroll_box.containedControl = scroll_window
        folder_area = scroll_window
    except Exception:
        scroll_box = None
        folder_area = window

    if not folders:
        folder_area.addElement(mset.UILabel("No folder/group-like objects found under Scene."))
        folder_area.addReturn()
    else:
        for folder in folders:
            uid = get_obj_uid(folder)
            if uid not in config.folder_enabled:
                config.folder_enabled[uid] = True

            cb = mset.UICheckBox()
            cb.value = config.folder_enabled.get(uid, True)

            def make_toggle(folder_uid, checkbox):
                def toggle():
                    config.folder_enabled[folder_uid] = checkbox.value
                return toggle

            cb.onChange = make_toggle(uid, cb)
            folder_area.addElement(cb)

            label_text = "{}  [{}]".format(get_obj_name(folder), type_name(folder))
            name_label = mset.UILabel(label_text)
            folder_area.addElement(name_label)
            folder_area.addReturn()

    if scroll_box is not None:
        window.addElement(scroll_box)
        window.addReturn()

    window.addReturn()

    # Action Buttons
    def run_render():
        if read_ui_settings():
            batch_render_current_scene()

    render_btn = mset.UIButton("Render Selected Folders")
    render_btn.onClick = run_render
    window.addElement(render_btn)

    close_btn = mset.UIButton("Close")
    close_btn.onClick = lambda: mset.shutdownPlugin()
    window.addElement(close_btn)


build_ui()
log("Batch Renderer Pro current-scene folder plugin loaded.")
