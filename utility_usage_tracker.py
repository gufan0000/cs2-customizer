import json
import os
import hashlib
from datetime import datetime, timedelta
from config import get_app_data_dir
from core.utils.logger import get_logger

logger = get_logger("UtilityUsageTracker")


class UtilityUsageTracker:
    """道具使用频率追踪器"""
    
    def __init__(self):
        # 数据文件路径
        self.data_dir = os.path.join(get_app_data_dir(), "utility_usage")
        self.stats_file = os.path.join(self.data_dir, "usage_stats.json")
        self.fingerprints_file = os.path.join(self.data_dir, "fingerprints.json")
        
        # 确保目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 加载数据
        self.usage_data = self.load_usage_data()
        self.fingerprints = self.load_fingerprints()
        
        # 配置参数
        self.decay_days = 30  # 衰减天数
        self.min_usage_for_sort = 1  # 最少使用次数参与排序（改为1，立即生效）
        self._hash_cache = {}  # 文件哈希缓存，避免重复计算
        
    def load_usage_data(self):
        """加载使用统计数据"""
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def load_fingerprints(self):
        """加载道具指纹数据"""
        if os.path.exists(self.fingerprints_file):
            try:
                with open(self.fingerprints_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_usage_data(self):
        """保存使用统计数据"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.usage_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存使用统计失败: {e}")
    
    def save_fingerprints(self):
        """保存道具指纹数据"""
        try:
            with open(self.fingerprints_file, 'w', encoding='utf-8') as f:
                json.dump(self.fingerprints, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存指纹数据失败: {e}")
    
    def calculate_file_hash(self, file_path):
        """计算文件哈希值"""
        if not os.path.exists(file_path):
            return None
        
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                # 读取文件前1MB以提高性能
                chunk = f.read(1024 * 1024)
                hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return None
    
    def get_utility_fingerprint(self, stand_path, aim_path):
        """获取道具指纹（基于两个图片文件），带缓存"""
        cache_key = f"{stand_path}|{aim_path}"
        if cache_key in self._hash_cache:
            return self._hash_cache[cache_key]

        stand_hash = self.calculate_file_hash(stand_path)
        aim_hash = self.calculate_file_hash(aim_path)

        if stand_hash and aim_hash:
            combined = f"{stand_hash}_{aim_hash}"
            result = hashlib.md5(combined.encode()).hexdigest()
            self._hash_cache[cache_key] = result
            return result
        
        # 降级方案：使用文件大小
        try:
            stand_size = os.path.getsize(stand_path) if os.path.exists(stand_path) else 0
            aim_size = os.path.getsize(aim_path) if os.path.exists(aim_path) else 0
            return f"size_{stand_size}_{aim_size}"
        except Exception:
            return None
    
    def record_usage(self, map_name, team, location, utility_name, stand_path, aim_path):
        """记录道具使用"""
        # 获取道具指纹
        fingerprint = self.get_utility_fingerprint(stand_path, aim_path)
        if not fingerprint:
            fingerprint = f"fallback_{map_name}_{team}_{location}_{utility_name}"
        
        # 初始化数据结构
        if map_name not in self.usage_data:
            self.usage_data[map_name] = {}
        if team not in self.usage_data[map_name]:
            self.usage_data[map_name][team] = {"locations": {}, "utilities": {}}
        
        # 记录位置使用
        if location not in self.usage_data[map_name][team]["locations"]:
            self.usage_data[map_name][team]["locations"][location] = {
                "usage_count": 0,
                "last_used": None,
                "weight": 0
            }
        
        location_data = self.usage_data[map_name][team]["locations"][location]
        location_data["usage_count"] += 1
        location_data["last_used"] = datetime.now().isoformat()
        location_data["weight"] = self.calculate_weight(
            location_data["usage_count"],
            location_data["last_used"]
        )
        
        # 记录道具使用
        if fingerprint not in self.usage_data[map_name][team]["utilities"]:
            self.usage_data[map_name][team]["utilities"][fingerprint] = {
                "name": utility_name,
                "usage_count": 0,
                "last_used": None,
                "location": location,
                "weight": 0
            }
        
        utility_data = self.usage_data[map_name][team]["utilities"][fingerprint]
        utility_data["usage_count"] += 1
        utility_data["last_used"] = datetime.now().isoformat()
        utility_data["name"] = utility_name  # 更新名称（可能已改名）
        utility_data["location"] = location  # 更新位置（可能已移动）
        utility_data["weight"] = self.calculate_weight(
            utility_data["usage_count"],
            utility_data["last_used"]
        )
        
        # 更新指纹库
        self.fingerprints[fingerprint] = {
            "map": map_name,
            "team": team,
            "location": location,
            "name": utility_name,
            "last_seen": datetime.now().isoformat()
        }
        
        # 保存数据
        self.save_usage_data()
        self.save_fingerprints()

        logger.info(f"记录道具使用: {map_name}/{team}/{location}/{utility_name} (使用次数: {utility_data['usage_count']})")
    
    def calculate_weight(self, usage_count, last_used_str):
        """计算排序权重"""
        if not last_used_str:
            return 0
        
        try:
            last_used = datetime.fromisoformat(last_used_str)
            days_ago = (datetime.now() - last_used).days
            
            # 时间衰减系数
            if days_ago <= 0:
                time_factor = 1.0
            elif days_ago <= 3:
                time_factor = 0.9
            elif days_ago <= 7:
                time_factor = 0.75
            elif days_ago <= 30:
                time_factor = 0.5
            else:
                time_factor = 0.25
            
            # 使用次数对数缩放（避免差距过大）
            import math
            count_factor = math.log(usage_count + 1) + 1
            
            return count_factor * time_factor
        except Exception:
            return usage_count
    
    def get_sorted_locations(self, map_name, team):
        """获取排序后的位置列表"""
        if (map_name not in self.usage_data or 
            team not in self.usage_data[map_name] or
            "locations" not in self.usage_data[map_name][team]):
            return None
        
        locations_data = self.usage_data[map_name][team]["locations"]
        
        # 过滤并排序
        sorted_locations = []
        for location, data in locations_data.items():
            if data["usage_count"] >= self.min_usage_for_sort:
                sorted_locations.append((location, data["weight"]))
        
        # 按权重降序排序
        sorted_locations.sort(key=lambda x: x[1], reverse=True)
        
        # 只返回位置名称列表
        return [loc[0] for loc in sorted_locations]
    
    def get_sorted_utilities(self, map_name, team, location):
        """获取排序后的道具列表"""
        if (map_name not in self.usage_data or 
            team not in self.usage_data[map_name] or
            "utilities" not in self.usage_data[map_name][team]):
            return None
        
        utilities_data = self.usage_data[map_name][team]["utilities"]
        
        # 过滤当前位置的道具并排序
        sorted_utilities = []
        for fingerprint, data in utilities_data.items():
            if data["location"] == location and data["usage_count"] >= self.min_usage_for_sort:
                sorted_utilities.append((data["name"], data["weight"]))
        
        # 按权重降序排序
        sorted_utilities.sort(key=lambda x: x[1], reverse=True)
        
        # 只返回道具名称列表
        return [util[0] for util in sorted_utilities]
    
    def merge_with_unsorted(self, sorted_list, full_list):
        """合并排序列表和完整列表，保持未使用的项目"""
        if not sorted_list:
            return full_list
        
        # 创建结果列表，先放排序的项目
        result = sorted_list.copy()
        
        # 添加未在排序列表中的项目
        for item in full_list:
            if item not in result:
                result.append(item)
        
        return result
    
    def cleanup_old_data(self, days=90):
        """清理旧数据"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        for map_name in list(self.usage_data.keys()):
            for team in list(self.usage_data[map_name].keys()):
                # 清理位置数据
                if "locations" in self.usage_data[map_name][team]:
                    for location in list(self.usage_data[map_name][team]["locations"].keys()):
                        data = self.usage_data[map_name][team]["locations"][location]
                        if data["last_used"]:
                            try:
                                last_used = datetime.fromisoformat(data["last_used"])
                                if last_used < cutoff_date:
                                    del self.usage_data[map_name][team]["locations"][location]
                            except Exception:
                                pass
                
                # 清理道具数据
                if "utilities" in self.usage_data[map_name][team]:
                    for fingerprint in list(self.usage_data[map_name][team]["utilities"].keys()):
                        data = self.usage_data[map_name][team]["utilities"][fingerprint]
                        if data["last_used"]:
                            try:
                                last_used = datetime.fromisoformat(data["last_used"])
                                if last_used < cutoff_date:
                                    del self.usage_data[map_name][team]["utilities"][fingerprint]
                            except Exception:
                                pass
        
        self.save_usage_data()
    
    def get_statistics(self, map_name=None, team=None):
        """获取使用统计信息"""
        stats = {
            "total_uses": 0,
            "unique_utilities": 0,
            "unique_locations": 0,
            "most_used_utility": None,
            "most_used_location": None
        }
        
        if map_name and map_name in self.usage_data:
            if team and team in self.usage_data[map_name]:
                data = self.usage_data[map_name][team]
                
                # 统计位置
                if "locations" in data:
                    stats["unique_locations"] = len(data["locations"])
                    max_location = max(
                        data["locations"].items(),
                        key=lambda x: x[1]["usage_count"],
                        default=(None, {"usage_count": 0})
                    )
                    if max_location[0]:
                        stats["most_used_location"] = {
                            "name": max_location[0],
                            "count": max_location[1]["usage_count"]
                        }
                
                # 统计道具
                if "utilities" in data:
                    stats["unique_utilities"] = len(data["utilities"])
                    for util_data in data["utilities"].values():
                        stats["total_uses"] += util_data["usage_count"]
                    
                    max_utility = max(
                        data["utilities"].items(),
                        key=lambda x: x[1]["usage_count"],
                        default=(None, {"usage_count": 0, "name": ""})
                    )
                    if max_utility[0]:
                        stats["most_used_utility"] = {
                            "name": max_utility[1]["name"],
                            "count": max_utility[1]["usage_count"]
                        }
        
        return stats


# 全局追踪器实例
_tracker_instance = None

def get_usage_tracker():
    """获取全局追踪器实例"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = UtilityUsageTracker()
    return _tracker_instance