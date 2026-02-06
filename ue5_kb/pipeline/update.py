"""
增量更新阶段

检测文件变更并仅更新修改的模块
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from .base import PipelineStage
from ..core.manifest import KBManifest, Hasher


class UpdateStage(PipelineStage):
    """增量更新阶段"""

    @property
    def stage_name(self) -> str:
        return "update"

    def get_output_path(self) -> Path:
        """
        获取输出文件路径

        Update 阶段没有独立的输出文件，
        返回 manifest 文件路径作为输出路径
        """
        return self.base_path / "KnowledgeBase" / ".kb_manifest.json"

    def is_completed(self) -> bool:
        """
        检查更新是否完成

        Returns:
            True 如果 manifest 文件存在
        """
        return self.get_output_path().exists()

    def run(self, **kwargs) -> Dict[str, Any]:
        """执行增量更新"""
        kb_path = self.base_path / "KnowledgeBase"
        old_manifest = KBManifest.load(kb_path)

        if not old_manifest:
            return {
                'error': 'No existing KB found',
                'incremental': False,
                'reason': 'Knowledge base manifest not found. Run init first.'
            }

        # 扫描当前状态
        current_modules = self._scan_current_modules()

        # 计算差异
        diff = self._compute_diff(old_manifest, current_modules)

        print(f"[Update] 变更检测结果:")
        print(f"  新增模块: {len(diff['added'])}")
        if diff['added']:
            for m in diff['added'][:5]:
                print(f"    - {m}")
            if len(diff['added']) > 5:
                print(f"    ... 还有 {len(diff['added']) - 5} 个")

        print(f"  修改模块: {len(diff['modified'])}")
        if diff['modified']:
            for m in diff['modified'][:5]:
                print(f"    - {m}")
            if len(diff['modified']) > 5:
                print(f"    ... 还有 {len(diff['modified']) - 5} 个")

        print(f"  删除模块: {len(diff['removed'])}")
        if diff['removed']:
            for m in diff['removed'][:5]:
                print(f"    - {m}")
            if len(diff['removed']) > 5:
                print(f"    ... 还有 {len(diff['removed']) - 5} 个")

        print(f"  未变更模块: {len(diff['unchanged'])}")

        if not any([diff['added'], diff['modified'], diff['removed']]):
            return {
                'incremental': True,
                'modules_updated': 0,
                'reason': 'No changes detected - KB is up to date'
            }

        # 对变更的模块运行 pipeline
        results = self._update_changed_modules(diff)

        # 更新 manifest
        new_manifest = self._merge_manifests(old_manifest, current_modules, diff)
        new_manifest.save(kb_path)

        return {
            'incremental': True,
            'modules_updated': len(diff['added']) + len(diff['modified']),
            'modules_removed': len(diff['removed']),
            'results': results
        }

    def check(self) -> Dict[str, Any]:
        """仅检查变更，不执行更新"""
        kb_path = self.base_path / "KnowledgeBase"
        old_manifest = KBManifest.load(kb_path)

        if not old_manifest:
            return {
                'error': 'No existing KB found',
                'incremental': False,
                'reason': 'Knowledge base manifest not found.'
            }

        current_modules = self._scan_current_modules()
        diff = self._compute_diff(old_manifest, current_modules)

        return {
            'can_update': True,
            'added_count': len(diff['added']),
            'modified_count': len(diff['modified']),
            'removed_count': len(diff['removed']),
            'unchanged_count': len(diff['unchanged']),
            'added_modules': diff['added'][:10],
            'modified_modules': diff['modified'][:10],
            'removed_modules': diff['removed'][:10]
        }

    def _scan_current_modules(self) -> List[Dict[str, Any]]:
        """扫描当前模块状态"""
        # 集成 DiscoverStage 逻辑
        from .discover import DiscoverStage

        discover = DiscoverStage(self.base_path)
        discover_result = discover.run()

        # 为每个模块计算哈希
        modules_with_hashes = []
        for module in discover_result.get('modules', []):
            module_hash = self._compute_module_hash(module)
            module['module_hash'] = module_hash
            modules_with_hashes.append(module)

        return modules_with_hashes

    def _compute_diff(
        self,
        old: KBManifest,
        current: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """计算新旧 manifest 的差异"""
        old_modules = set(old.modules.keys())
        current_map = {m['name']: m for m in current}
        new_modules = set(current_map.keys())

        added = new_modules - old_modules
        removed = old_modules - new_modules

        # 检查修改（通过哈希比较）
        modified = []
        unchanged = []

        for module_name in old_modules & new_modules:
            old_hash = old.modules[module_name].get('hash', '')
            new_hash = current_map[module_name].get('module_hash', '')

            if old_hash != new_hash:
                modified.append(module_name)
            else:
                unchanged.append(module_name)

        return {
            'added': sorted(list(added)),
            'modified': sorted(modified),
            'removed': sorted(list(removed)),
            'unchanged': sorted(unchanged)
        }

    def _compute_module_hash(self, module_info: Dict[str, Any]) -> str:
        """计算单个模块的哈希"""
        build_cs_path = Path(module_info['absolute_path'])
        module_dir = build_cs_path.parent

        # 查找所有源文件
        source_files = []
        for ext in ['*.h', '*.cpp', '*.inl']:
            source_files.extend(module_dir.rglob(ext))

        return Hasher.compute_module_hash(build_cs_path, source_files)

    def _update_changed_modules(self, diff: Dict[str, List[str]]) -> Dict[str, Any]:
        """对变更的模块运行 pipeline"""
        # 这里需要集成 PipelineCoordinator 来运行特定模块的更新
        # 由于实现较复杂，这里返回摘要信息
        # 实际实现需要调用 extract/analyze/build 阶段

        changed_modules = diff['added'] + diff['modified']

        results = {
            'modules_to_update': changed_modules,
            'status': 'update_required'
        }

        return results

    def _merge_manifests(
        self,
        old: KBManifest,
        current: List[Dict[str, Any]],
        diff: Dict[str, List[str]]
    ) -> KBManifest:
        """合并新旧 manifest，生成新的 manifest"""
        from datetime import datetime

        current_map = {m['name']: m for m in current}

        # 更新模块信息
        new_modules = {}
        for module_name in old.modules.keys():
            if module_name in diff['unchanged']:
                # 未变更的模块保留原信息
                new_modules[module_name] = old.modules[module_name]
            elif module_name in diff['modified']:
                # 修改的模块使用新哈希
                new_modules[module_name] = {
                    'hash': current_map[module_name].get('module_hash', ''),
                    'indexed_at': datetime.now().isoformat(),
                    'file_count': old.modules[module_name].get('file_count', 0)
                }

        # 添加新模块
        for module_name in diff['added']:
            new_modules[module_name] = {
                'hash': current_map[module_name].get('module_hash', ''),
                'indexed_at': datetime.now().isoformat(),
                'file_count': 0  # 需要从 extract 阶段获取
            }

        # 创建新 manifest
        new_manifest = KBManifest(
            kb_version=old.kb_version,
            engine_version=old.engine_version,
            engine_path=old.engine_path,
            plugin_name=old.plugin_name,
            created_at=old.created_at,
            last_updated=datetime.now().isoformat(),
            build_mode=old.build_mode,
            tool_version=old.tool_version,
            files=old.files,  # 需要从 extract 阶段更新
            modules=new_modules,
            statistics=old.statistics
        )

        return new_manifest
