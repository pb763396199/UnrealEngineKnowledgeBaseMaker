"""
测试 .Build.cs 文件扫描逻辑
"""
from pathlib import Path

engine_path = Path(r"D:\Unreal Engine\UnrealEngine51_500\Engine")

print(f"引擎路径: {engine_path}")
print(f"路径存在: {engine_path.exists()}")
print()

# 测试各个目录
for target in ['Source', 'Plugins', 'Platforms']:
    target_path = engine_path / target
    print(f"{target}/ 存在: {target_path.exists()}")

    if target_path.exists():
        # 搜索 .Build.cs 文件
        build_cs_files = list(target_path.rglob('*.Build.cs'))
        print(f"  找到 {len(build_cs_files)} 个 .Build.cs 文件")

        # 显示前 5 个
        for build_cs in build_cs_files[:5]:
            # 计算相对路径
            rel_path = build_cs.relative_to(engine_path)
            parts = list(rel_path.parts)

            # 推导分类
            if parts[0] == 'Source':
                category = parts[1] if len(parts) >= 2 else 'Unknown'
            elif parts[0] == 'Plugins':
                category = f"Plugins.{parts[1]}.{parts[2]}" if len(parts) >= 3 else 'Plugins.Unknown'
            elif parts[0] == 'Platforms':
                category = f"Platforms.{parts[1]}" if len(parts) >= 2 else 'Platforms'
            else:
                category = 'Unknown'

            module_name = build_cs.stem
            print(f"  - {module_name:30} | {category}")

        if len(build_cs_files) > 5:
            print(f"  ... 还有 {len(build_cs_files) - 5} 个文件")

    print()
