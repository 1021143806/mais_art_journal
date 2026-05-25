"""mais_art_journal 插件冒烟测试

测试插件的基本功能是否正常工作：
1. 配置加载
2. 模型注册表
3. 风格注册表
4. 提示词构建器
5. 自拍提示词生成
"""
import sys
from pathlib import Path

# 添加插件路径到 sys.path
plugin_dir = Path(__file__).parent.parent
sys.path.insert(0, str(plugin_dir))

def test_config_loading():
    """测试配置加载"""
    print("测试 1: 配置加载...")
    try:
        from core.config.models import MaisArtConfig

        # 兼容 Python 3.11+ (tomllib) 和 3.10- (tomli)
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        config_path = plugin_dir / "config.toml"
        if not config_path.exists():
            print("  ❌ config.toml 不存在")
            return False

        with open(config_path, "rb") as f:
            config_dict = tomllib.load(f)

        config = MaisArtConfig(**config_dict)
        print(f"  ✅ 配置加载成功")
        print(f"     - 插件名称: {config.plugin.name}")
        print(f"     - 配置版本: {config.plugin.config_version}")
        print(f"     - 默认模型: {config.basic.default_model}")
        print(f"     - 模型数量: {len(config.models.items)}")
        print(f"     - 风格数量: {len(config.styles.items)}")
        return True
    except Exception as e:
        print(f"  ❌ 配置加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_model_registry():
    """测试模型注册表"""
    print("\n测试 2: 模型注册表...")
    try:
        from core.config.model_registry import model_exists
        from core.config.models import MaisArtConfig

        # 兼容 Python 3.11+ (tomllib) 和 3.10- (tomli)
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        config_path = plugin_dir / "config.toml"
        with open(config_path, "rb") as f:
            config_dict = tomllib.load(f)
        config = MaisArtConfig(**config_dict)

        # 创建一个模拟的 plugin 对象
        class MockPlugin:
            def __init__(self, cfg):
                self.config = cfg

            def get_config(self, key, default=None):
                """模拟 plugin.get_config 方法"""
                parts = key.split(".")
                obj = self.config

                for part in parts:
                    if hasattr(obj, part):
                        obj = getattr(obj, part)
                    elif isinstance(obj, dict) and part in obj:
                        obj = obj[part]
                    else:
                        return default

                # 如果是 Pydantic 模型，转换为字典
                if hasattr(obj, "model_dump"):
                    return obj.model_dump(mode="python")

                return obj

        plugin = MockPlugin(config)

        # 测试存在的模型
        if model_exists(plugin, "model1"):
            print(f"  ✅ model1 存在")
        else:
            print(f"  ❌ model1 应该存在但检测不到")
            return False

        # 测试不存在的模型
        if not model_exists(plugin, "model999"):
            print(f"  ✅ model999 不存在（正确）")
        else:
            print(f"  ❌ model999 不应该存在")
            return False

        return True
    except Exception as e:
        print(f"  ❌ 模型注册表测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_style_registry():
    """测试风格注册表"""
    print("\n测试 3: 风格注册表...")
    try:
        from core.config.style_registry import resolve_style_alias, get_style_prompt
        from core.config.models import MaisArtConfig

        # 兼容 Python 3.11+ (tomllib) 和 3.10- (tomli)
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        config_path = plugin_dir / "config.toml"
        with open(config_path, "rb") as f:
            config_dict = tomllib.load(f)
        config = MaisArtConfig(**config_dict)

        class MockPlugin:
            def __init__(self, cfg):
                self.config = cfg

            def get_config(self, key, default=None):
                """模拟 plugin.get_config 方法"""
                parts = key.split(".")
                obj = self.config

                for part in parts:
                    if hasattr(obj, part):
                        obj = getattr(obj, part)
                    elif isinstance(obj, dict) and part in obj:
                        obj = obj[part]
                    else:
                        return default

                # 如果是 Pydantic 模型，转换为字典
                if hasattr(obj, "model_dump"):
                    return obj.model_dump(mode="python")

                return obj

        plugin = MockPlugin(config)

        # 测试风格解析
        style = resolve_style_alias(plugin, "cartoon")
        if style == "cartoon":
            print(f"  ✅ cartoon 风格解析成功")
        else:
            print(f"  ❌ cartoon 风格解析失败")
            return False

        # 测试风格提示词
        prompt = get_style_prompt(plugin, "cartoon")
        if prompt and len(prompt) > 0:
            print(f"  ✅ cartoon 风格提示词获取成功: {prompt[:50]}...")
        else:
            print(f"  ❌ cartoon 风格提示词获取失败")
            return False

        # 测试不存在的风格
        unknown = resolve_style_alias(plugin, "unknown_style_xyz")
        if unknown is None:
            print(f"  ✅ unknown_style_xyz 不存在（正确）")
        else:
            print(f"  ❌ unknown_style_xyz 不应该存在")
            return False

        return True
    except Exception as e:
        print(f"  ❌ 风格注册表测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_selfie_prompt_builder():
    """测试自拍提示词构建器"""
    print("\n测试 4: 自拍提示词构建器...")
    try:
        from core.prompts.selfie_prompt_builder import (
            get_scene_prompt_for_style,
            get_hand_actions_for_style,
            build_hand_prompt_for_style,
            sanitize_hand_action_for_style,
        )

        # 测试三种风格的场景提示词
        for style in ["standard", "mirror", "photo"]:
            scene = get_scene_prompt_for_style(style)
            if scene and len(scene) > 0:
                print(f"  ✅ {style} 场景提示词: {len(scene)} 字符")
            else:
                print(f"  ❌ {style} 场景提示词获取失败")
                return False

        # 测试手部动作池
        for style in ["standard", "mirror", "photo"]:
            actions = get_hand_actions_for_style(style)
            if actions and len(actions) > 0:
                print(f"  ✅ {style} 手部动作池: {len(actions)} 个动作")
            else:
                print(f"  ❌ {style} 手部动作池为空")
                return False

        # 测试手部提示词构建
        hand_prompt = build_hand_prompt_for_style("peace sign with one hand", "standard")
        if hand_prompt and "phone" in hand_prompt.lower():
            print(f"  ✅ standard 手部提示词包含 phone 关键词")
        else:
            print(f"  ❌ standard 手部提示词构建失败")
            return False

        # 测试 sanitize（清洗冲突关键词）
        dirty = "holding phone with both hands"
        clean = sanitize_hand_action_for_style(dirty, "standard")
        if clean != dirty:
            print(f"  ✅ sanitize 成功清洗冲突关键词")
        else:
            print(f"  ⚠️  sanitize 未清洗冲突关键词（可能是预期行为）")

        return True
    except Exception as e:
        print(f"  ❌ 自拍提示词构建器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_imports():
    """测试关键模块导入"""
    print("\n测试 5: 关键模块导入...")
    try:
        modules = [
            "core.config",
            "core.api_clients.base_client",
            "core.api_clients.openai_client",
            "core.api_clients.modelscope_client",
            "core.pipeline",
            "core.commands.registry",
            "core.commands.dispatcher",
            "core.state",
            "core.utils.recall_utils",
            "core.utils.cache_manager",
            "core.prompts.selfie_prompt_builder",
        ]

        for module_name in modules:
            try:
                __import__(module_name)
                print(f"  ✅ {module_name}")
            except Exception as e:
                print(f"  ❌ {module_name}: {e}")
                return False

        return True
    except Exception as e:
        print(f"  ❌ 模块导入测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("mais_art_journal 插件冒烟测试")
    print("=" * 60)

    results = []

    # 运行所有测试
    results.append(("配置加载", test_config_loading()))
    results.append(("模型注册表", test_model_registry()))
    results.append(("风格注册表", test_style_registry()))
    results.append(("自拍提示词构建器", test_selfie_prompt_builder()))
    results.append(("关键模块导入", test_imports()))

    # 输出总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
