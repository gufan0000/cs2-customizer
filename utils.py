from resource_manager import ResourceManager

# 资源路径 (用于PyInstaller打包)
def resource_path(relative_path):
    # 统一使用ResourceManager处理资源路径
    return ResourceManager.get_exe_resource_path(relative_path)