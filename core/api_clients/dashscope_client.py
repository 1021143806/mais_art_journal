"""阿里百炼 DashScope API 客户端

支持阿里云百炼平台的多模态图片生成接口，覆盖：
- 通义千问：``qwen-image-2.0-pro`` / ``qwen-image-edit-*``
- 万相：``wan2.5-i2i-preview`` / ``wan2.6-image`` / ``wan2.6-t2i`` / ``wan2.7-image-pro``
- Z-Image：``z-image-turbo``
- 可灵：``kling/kling-v3-image-generation`` / ``kling-v3-omni-image-generation``

统一请求结构（与 OpenAI 完全不同）：

    {
        "model": <model_id>,
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"text": <prompt>},
                    {"image": <url_or_data_uri>},   # 图生图时追加，可多张
                ],
            }]
        },
        "parameters": {
            "size": "2K" | "1024*1024",     # DashScope 用 * 而非 x，也支持 1K/2K/4K
            "n": 1,
            "watermark": false,
            "prompt_extend": true,
            "negative_prompt": "...",
        }
    }

同步 / 异步判定：
- 用户显式配 ``dashscope_async = true`` → 发请求时带 ``X-DashScope-Async: enable``
- 已知异步端点（``/image2image/`` 或 ``/image-generation/``）也自动开启异步
- 响应 ``output.task_id`` 非空 → 走轮询路径

model_config 字段（DashScope 专属）：
- ``base_url``: 默认 ``https://dashscope.aliyuncs.com``
- ``endpoint_path``: 可选，自定义端点 path
    * 留空 → ``/api/v1/services/aigc/multimodal-generation/generation``（千问/万相2.6+/Z-Image）
    * ``/api/v1/services/aigc/image2image/image-synthesis`` → 万相 2.5 i2i（强制异步）
    * ``/api/v1/services/aigc/image-generation/generation`` → 可灵（强制异步）
- ``dashscope_async``: 是否启用异步；可选，默认 False
- ``prompt_extend``: 是否开启智能扩写；默认 True
- ``watermark``: 默认 False
"""
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import requests

from .base_client import BaseApiClient, NonRetryableError, logger


# 默认端点（千问 / 万相 2.6+ / Z-Image）
_DEFAULT_ENDPOINT = "/api/v1/services/aigc/multimodal-generation/generation"

# DashScope 通用任务查询端点
_TASK_QUERY_PATH = "/api/v1/tasks/{task_id}"

# 轮询参数
_POLL_INTERVAL_SECONDS = 3
_POLL_MAX_ATTEMPTS = 60  # 最长 ~3 分钟

# 已知强制异步的端点路径片段
_ASYNC_ENDPOINT_HINTS = ("/image2image/", "/image-generation/")


class DashScopeClient(BaseApiClient):
    """阿里百炼 DashScope API 客户端"""

    format_name = "dashscope"

    def _make_request(
        self,
        prompt: str,
        model_config: Dict[str, Any],
        size: str,
        strength: float = None,
        input_image_base64: str = None,
    ) -> Tuple[bool, str]:
        """发送 DashScope 请求"""
        try:
            base_url = model_config.get("base_url", "https://dashscope.aliyuncs.com").rstrip("/")
            api_key = model_config.get("api_key", "").replace("Bearer ", "").strip()
            model_name = model_config.get("model", "")
            endpoint_path = (model_config.get("endpoint_path") or "").strip() or _DEFAULT_ENDPOINT
            if not endpoint_path.startswith("/"):
                endpoint_path = "/" + endpoint_path

            if not api_key or api_key in ("xxxxxxxxxxxxxx", "YOUR_API_KEY_HERE"):
                logger.error(f"{self.log_prefix} (DashScope) API 密钥未配置或无效")
                return False, "DashScope API 密钥未配置"

            if not model_name:
                logger.error(f"{self.log_prefix} (DashScope) model 字段为空")
                return False, "DashScope model 字段为空"

            endpoint = f"{base_url}{endpoint_path}"

            # 提示词拼接
            custom_prompt_add = model_config.get("custom_prompt_add", "") or ""
            full_prompt = f"{prompt}{custom_prompt_add}"
            negative_prompt_add = model_config.get("negative_prompt_add", "") or ""

            # content 数组：text + 可选图片
            content: List[Dict[str, Any]] = [{"text": full_prompt}]

            if input_image_base64:
                image_uri = self._prepare_image_data_uri(input_image_base64)
                content.append({"image": image_uri})
                logger.info(f"{self.log_prefix} (DashScope) 图生图模式")
            else:
                logger.info(f"{self.log_prefix} (DashScope) 文生图模式")

            # 标准化尺寸（DashScope 用 *）
            normalized_size = self._normalize_size(size)

            # parameters 块
            parameters: Dict[str, Any] = {
                "n": int(model_config.get("n", 1) or 1),
                "watermark": bool(model_config.get("watermark", False)),
                "prompt_extend": bool(model_config.get("prompt_extend", True)),
            }
            if normalized_size:
                parameters["size"] = normalized_size

            seed = model_config.get("seed", -1)
            if seed is not None and seed != -1:
                try:
                    parameters["seed"] = int(seed)
                except (ValueError, TypeError):
                    pass

            if negative_prompt_add:
                parameters["negative_prompt"] = negative_prompt_add

            # 构建请求体
            request_data: Dict[str, Any] = {
                "model": model_name,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": content,
                        }
                    ]
                },
                "parameters": parameters,
            }

            # 异步判定
            user_async = bool(model_config.get("dashscope_async", False))
            is_async_endpoint = any(hint in endpoint_path for hint in _ASYNC_ENDPOINT_HINTS)
            should_use_async = user_async or is_async_endpoint

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            if should_use_async:
                headers["X-DashScope-Async"] = "enable"

            # verbose 调试
            verbose_debug = self.ctx.get_config("basic.enable_verbose_debug", False)
            if verbose_debug:
                logger.info(f"{self.log_prefix} (DashScope) 端点: {endpoint}")
                logger.info(f"{self.log_prefix} (DashScope) 请求体: {self._safe_dump(request_data)}")

            logger.info(
                f"{self.log_prefix} (DashScope) 发起请求: model={model_name}, "
                f"async={should_use_async}, size={normalized_size or '<default>'}"
            )

            proxy_config = self._get_proxy_config()

            # 发请求
            post_result = self._post_json(endpoint, request_data, headers, proxy_config)
            if post_result is None:
                return False, "DashScope HTTP 请求失败"

            status_code, body_text = post_result

            if not (200 <= status_code < 300):
                # 4xx 视为不可重试（鉴权 / 参数 / 内容审核）
                err_msg = self._extract_error_message(body_text) or body_text[:200]
                logger.error(f"{self.log_prefix} (DashScope) HTTP {status_code}: {err_msg}")
                if 400 <= status_code < 500:
                    raise NonRetryableError(f"DashScope HTTP {status_code}: {err_msg}")
                return False, f"HTTP {status_code}: {err_msg}"

            try:
                resp_data = json.loads(body_text)
            except json.JSONDecodeError as e:
                logger.error(f"{self.log_prefix} (DashScope) JSON 解析失败: {e}; preview: {body_text[:200]}")
                return False, "响应 JSON 解析失败"

            if verbose_debug:
                logger.info(f"{self.log_prefix} (DashScope) 响应预览: {self._safe_dump(resp_data)[:500]}")

            output = resp_data.get("output") if isinstance(resp_data, dict) else None
            if not isinstance(output, dict):
                logger.error(f"{self.log_prefix} (DashScope) 响应无 output 字段: {body_text[:200]}")
                return False, "响应缺少 output 字段"

            # 异步路径：output.task_id 非空时轮询
            task_id = output.get("task_id")
            if isinstance(task_id, str) and task_id:
                logger.info(f"{self.log_prefix} (DashScope) 异步任务 ID: {task_id}，开始轮询")
                return self._poll_task(base_url, task_id, api_key, proxy_config)

            # 同步路径：从 output.choices[0].message.content 或 output.results 提取
            image_url = self._extract_sync_image(output)
            if image_url:
                logger.info(f"{self.log_prefix} (DashScope) 图片生成成功: {image_url[:80]}…")
                return True, image_url

            logger.error(f"{self.log_prefix} (DashScope) 响应无图片字段: {body_text[:300]}")
            return False, "DashScope 响应未找到图片"

        except NonRetryableError:
            raise
        except Exception as e:
            logger.error(f"{self.log_prefix} (DashScope) 请求异常: {e!r}", exc_info=True)
            return False, f"DashScope 请求异常: {str(e)[:100]}"

    # ==================== 内部工具 ====================

    @staticmethod
    def _normalize_size(size: str) -> str:
        """DashScope 尺寸格式标准化

        - "1024x1024" / "1024X1024" → "1024*1024"
        - "1K" / "2K" / "4K" → 透传（万相 2.7 / Z-Image / 可灵支持）
        - "1024*1024" → 透传
        - "" / None → ""（让 DashScope 走模型默认）
        """
        if not size:
            return ""
        s = str(size).strip()
        if not s:
            return ""
        # 语义化分辨率
        if s.upper() in ("512", "1K", "2K", "4K"):
            return s.upper()
        # 像素格式：x → *
        if "x" in s.lower():
            return s.lower().replace("x", "*")
        return s

    def _post_json(
        self,
        endpoint: str,
        data: Dict[str, Any],
        headers: Dict[str, str],
        proxy_config: Optional[Dict[str, Any]],
    ) -> Optional[Tuple[int, str]]:
        """POST JSON 请求，返回 (status_code, body_text)；连接错误返回 None"""
        try:
            body_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(endpoint, data=body_bytes, headers=headers, method="POST")

            if proxy_config:
                proxy_handler = urllib.request.ProxyHandler({
                    "http": proxy_config["http"],
                    "https": proxy_config["https"],
                })
                opener = urllib.request.build_opener(proxy_handler)
            else:
                opener = urllib.request.build_opener()

            timeout = int((proxy_config or {}).get("timeout", 600))

            try:
                with opener.open(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    return resp.status, body
            except urllib.error.HTTPError as he:
                body = ""
                try:
                    body = he.read().decode("utf-8", errors="replace") if he.fp else ""
                except Exception:
                    pass
                return he.code, body
        except Exception as e:
            logger.error(f"{self.log_prefix} (DashScope) HTTP 请求异常: {e}")
            return None

    @staticmethod
    def _extract_error_message(body_text: str) -> str:
        """尝试从 DashScope 错误响应里抽出 message 字段"""
        if not body_text:
            return ""
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError:
            return ""
        if not isinstance(data, dict):
            return ""
        # DashScope 错误结构：{"code": "...", "message": "...", "request_id": "..."}
        msg = data.get("message")
        if isinstance(msg, str) and msg:
            return msg
        # 兼容嵌套：{"output": {"message": "..."}}
        output = data.get("output")
        if isinstance(output, dict):
            msg = output.get("message") or output.get("error")
            if isinstance(msg, str) and msg:
                return msg
        return ""

    @staticmethod
    def _extract_sync_image(output: Dict[str, Any]) -> Optional[str]:
        """从同步响应的 output 字段提取图片 URL

        DashScope 同步响应有两种常见形态：
        1. ``output.choices[0].message.content[].image``  (多模态生成接口)
        2. ``output.results[].url``                        (image2image / 部分变体)
        """
        # 形态 1：choices → message → content[]
        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message", {}) or {}
                content = msg.get("content")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            url = item.get("image") or item.get("image_url")
                            if isinstance(url, str) and url:
                                return url
                elif isinstance(content, str) and content.startswith(("http://", "https://")):
                    return content

        # 形态 2：results[]
        results = output.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                url = first.get("url") or first.get("image_url") or first.get("image")
                if isinstance(url, str) and url:
                    return url

        return None

    def _poll_task(
        self,
        base_url: str,
        task_id: str,
        api_key: str,
        proxy_config: Optional[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        """轮询 DashScope 异步任务，最长 ~3 分钟"""
        url = f"{base_url}{_TASK_QUERY_PATH.format(task_id=task_id)}"
        headers = {"Authorization": f"Bearer {api_key}"}

        last_status = ""
        for attempt in range(_POLL_MAX_ATTEMPTS):
            try:
                kwargs: Dict[str, Any] = {"url": url, "headers": headers, "timeout": 15}
                if proxy_config:
                    kwargs["proxies"] = {
                        "http": proxy_config["http"],
                        "https": proxy_config["https"],
                    }

                resp = requests.get(**kwargs)
                if resp.status_code != 200:
                    logger.warning(
                        f"{self.log_prefix} (DashScope) 任务查询 HTTP {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                    time.sleep(_POLL_INTERVAL_SECONDS)
                    continue

                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    time.sleep(_POLL_INTERVAL_SECONDS)
                    continue

                output = data.get("output") if isinstance(data, dict) else None
                if not isinstance(output, dict):
                    time.sleep(_POLL_INTERVAL_SECONDS)
                    continue

                status = str(output.get("task_status", "")).upper()

                if status in ("SUCCEEDED", "SUCCESS"):
                    image_url = self._extract_task_image(output)
                    if image_url:
                        logger.info(
                            f"{self.log_prefix} (DashScope) 任务 {task_id} 完成: {image_url[:80]}…"
                        )
                        return True, image_url
                    logger.error(f"{self.log_prefix} (DashScope) 任务成功但无图片: {output}")
                    return False, "任务成功但未找到图片"

                if status in ("FAILED", "CANCELED", "CANCELLED", "UNKNOWN_ERROR", "REJECTED"):
                    err = (
                        output.get("message")
                        or output.get("error")
                        or output.get("error_message")
                        or "任务失败"
                    )
                    logger.error(f"{self.log_prefix} (DashScope) 任务失败: {err}")
                    # 4xx 类的失败视为不可重试
                    raise NonRetryableError(f"DashScope 任务失败: {err}")

                # PENDING / RUNNING / SUSPENDED 等
                if status != last_status:
                    logger.info(f"{self.log_prefix} (DashScope) 任务状态: {status}")
                    last_status = status
                time.sleep(_POLL_INTERVAL_SECONDS)

            except NonRetryableError:
                raise
            except Exception as e:
                logger.warning(f"{self.log_prefix} (DashScope) 轮询异常: {e}")
                time.sleep(_POLL_INTERVAL_SECONDS)

        logger.error(f"{self.log_prefix} (DashScope) 任务 {task_id} 轮询超时")
        return False, "DashScope 任务轮询超时"

    @staticmethod
    def _extract_task_image(output: Dict[str, Any]) -> Optional[str]:
        """从任务查询响应的 output 字段提取图片 URL

        DashScope 异步任务标准格式：``output.results[].url``
        部分接口会返回 ``output.images[].url`` 或 ``output.url`` 等变体，全部覆盖。
        """
        # 标准：results[].url
        results = output.get("results")
        if isinstance(results, list) and results:
            for item in results:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("image_url") or item.get("image")
                    if isinstance(url, str) and url:
                        return url

        # 变体：images[].url
        images = output.get("images")
        if isinstance(images, list) and images:
            for item in images:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("image_url")
                    if isinstance(url, str) and url:
                        return url
                elif isinstance(item, str) and item:
                    return item

        # 兜底：直接的 url 字段
        url = output.get("url") or output.get("image_url")
        if isinstance(url, str) and url:
            return url

        return None

    @staticmethod
    def _safe_dump(data: Dict[str, Any]) -> str:
        """脱敏 dump 请求体 / 响应（隐藏图片 base64）"""
        try:
            cloned = json.loads(json.dumps(data, ensure_ascii=False))
        except Exception:
            return "<dump 失败>"

        def _scrub(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in list(obj.items()):
                    if isinstance(v, str) and v.startswith("data:image"):
                        obj[k] = "[BASE64_IMAGE…]"
                    elif isinstance(v, (dict, list)):
                        _scrub(v)
            elif isinstance(obj, list):
                for item in obj:
                    _scrub(item)

        _scrub(cloned)
        try:
            return json.dumps(cloned, ensure_ascii=False)
        except Exception:
            return "<dump 失败>"
