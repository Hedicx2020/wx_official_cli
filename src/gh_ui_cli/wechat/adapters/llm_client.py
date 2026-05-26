#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大模型调用客户端 - 支持多种LLM接入

支持的模型:
- OpenAI (GPT-3.5, GPT-4)
- 通义千问 (阿里云)
- 文心一言 (百度)
- DeepSeek
- Claude (Anthropic)
- Ollama (本地模型)
- 智谱AI (GLM系列)
"""

import json
import requests
from typing import Optional, Dict, Any, Generator
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class LLMConfig:
    """LLM配置"""
    provider: str  # openai, qwen, wenxin, deepseek, claude, ollama, zhipu
    api_key: str
    api_base: Optional[str] = None  # 自定义API地址
    model: Optional[str] = None  # 模型名称
    temperature: float = 0.7
    max_tokens: int = 2000
    
    # 百度文心一言特有
    secret_key: Optional[str] = None


class BaseLLMClient(ABC):
    """LLM客户端基类"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
    
    @abstractmethod
    def chat(self, messages: list, context: str = None) -> str:
        """发送聊天消息"""
        pass
    
    @abstractmethod
    def stream_chat(self, messages: list, context: str = None) -> Generator[str, None, None]:
        """流式聊天"""
        pass
    
    def build_messages_with_context(self, messages: list, context: str = None) -> list:
        """构建包含上下文的消息"""
        result = []
        
        # 如果有搜索结果上下文，添加系统提示
        if context:
            system_prompt = f"""你是一个微信聊天记录分析助手。用户会提供一些聊天记录，请根据这些记录回答用户的问题。

以下是用户搜索到的聊天记录：
---
{context}
---

请根据以上聊天记录内容回答用户的问题。如果问题与聊天记录无关，请礼貌地提示用户。"""
            result.append({"role": "system", "content": system_prompt})
        
        result.extend(messages)
        return result


class OpenAIClient(BaseLLMClient):
    """OpenAI客户端 (兼容OpenAI API格式的服务)"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "https://api.openai.com/v1"
        self.model = config.model or "gpt-3.5-turbo"
    
    def _build_url(self) -> str:
        """构建API请求URL"""
        base = self.api_base.rstrip('/')
        if base.endswith('/chat/completions'):
            return base
        return f"{base}/chat/completions"
    
    def chat(self, messages: list, context: str = None) -> str:
        messages = self.build_messages_with_context(messages, context)
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens
        }
        
        url = self._build_url()
        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code != 200:
            error_msg = response.text[:500] if response.text else '无响应内容'
            raise Exception(f"API请求失败: {response.status_code} - {error_msg}")
        
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    def stream_chat(self, messages: list, context: str = None) -> Generator[str, None, None]:
        messages = self.build_messages_with_context(messages, context)
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True
        }
        
        url = self._build_url()
        response = requests.post(
            url,
            headers=headers,
            json=data,
            stream=True,
            timeout=60
        )
        
        if response.status_code != 200:
            error_msg = response.text[:500] if response.text else '无响应内容'
            raise Exception(f"API请求失败: {response.status_code} - {error_msg}")
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith("data: "):
                    line = line[6:]
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue


class QwenClient(BaseLLMClient):
    """通义千问客户端 (阿里云)"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "https://dashscope.aliyuncs.com/api/v1"
        self.model = config.model or "qwen-turbo"
    
    def chat(self, messages: list, context: str = None) -> str:
        messages = self.build_messages_with_context(messages, context)
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "input": {
                "messages": messages
            },
            "parameters": {
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "result_format": "message"
            }
        }
        
        response = requests.post(
            f"{self.api_base}/services/aigc/text-generation/generation",
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        result = response.json()
        
        if "output" not in result:
            raise Exception(f"API响应异常: {result}")
        
        return result["output"]["choices"][0]["message"]["content"]
    
    def stream_chat(self, messages: list, context: str = None) -> Generator[str, None, None]:
        messages = self.build_messages_with_context(messages, context)
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable"
        }
        
        data = {
            "model": self.model,
            "input": {
                "messages": messages
            },
            "parameters": {
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "result_format": "message",
                "incremental_output": True
            }
        }
        
        response = requests.post(
            f"{self.api_base}/services/aigc/text-generation/generation",
            headers=headers,
            json=data,
            stream=True,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith("data:"):
                    line = line[5:].strip()
                    try:
                        data = json.loads(line)
                        if "output" in data:
                            content = data["output"]["choices"][0]["message"]["content"]
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue


class WenxinClient(BaseLLMClient):
    """文心一言客户端 (百度)"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_key = config.api_key
        self.secret_key = config.secret_key
        self.model = config.model or "ernie-bot-turbo"
        self._access_token = None
    
    def _get_access_token(self) -> str:
        """获取百度API访问令牌"""
        if self._access_token:
            return self._access_token
        
        url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={self.api_key}&client_secret={self.secret_key}"
        
        response = requests.post(url, timeout=30)
        
        if response.status_code != 200:
            raise Exception(f"获取access_token失败: {response.text}")
        
        result = response.json()
        self._access_token = result["access_token"]
        return self._access_token
    
    def _get_api_url(self) -> str:
        """根据模型获取API URL"""
        model_urls = {
            "ernie-bot": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions",
            "ernie-bot-turbo": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/eb-instant",
            "ernie-bot-4": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions_pro",
        }
        return model_urls.get(self.model, model_urls["ernie-bot-turbo"])
    
    def chat(self, messages: list, context: str = None) -> str:
        messages = self.build_messages_with_context(messages, context)
        
        # 百度API不支持system角色，需要转换
        converted_messages = []
        system_content = ""
        
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                converted_messages.append(msg)
        
        # 如果有system内容，合并到第一条user消息
        if system_content and converted_messages:
            if converted_messages[0]["role"] == "user":
                converted_messages[0]["content"] = f"{system_content}\n\n{converted_messages[0]['content']}"
        
        access_token = self._get_access_token()
        url = f"{self._get_api_url()}?access_token={access_token}"
        
        data = {
            "messages": converted_messages,
            "temperature": self.config.temperature
        }
        
        response = requests.post(url, json=data, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        result = response.json()
        
        if "error_code" in result:
            raise Exception(f"API错误: {result.get('error_msg', '未知错误')}")
        
        return result["result"]
    
    def stream_chat(self, messages: list, context: str = None) -> Generator[str, None, None]:
        messages = self.build_messages_with_context(messages, context)
        
        # 转换消息格式
        converted_messages = []
        system_content = ""
        
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                converted_messages.append(msg)
        
        if system_content and converted_messages:
            if converted_messages[0]["role"] == "user":
                converted_messages[0]["content"] = f"{system_content}\n\n{converted_messages[0]['content']}"
        
        access_token = self._get_access_token()
        url = f"{self._get_api_url()}?access_token={access_token}"
        
        data = {
            "messages": converted_messages,
            "temperature": self.config.temperature,
            "stream": True
        }
        
        response = requests.post(url, json=data, stream=True, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith("data: "):
                    line = line[6:]
                    try:
                        data = json.loads(line)
                        if "result" in data:
                            yield data["result"]
                    except json.JSONDecodeError:
                        continue


class DeepSeekClient(OpenAIClient):
    """DeepSeek客户端 (使用OpenAI兼容API)"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "https://api.deepseek.com"
        self.model = config.model or "deepseek-chat"


class ClaudeClient(BaseLLMClient):
    """Claude客户端 (Anthropic)"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "https://api.anthropic.com"
        self.model = config.model or "claude-3-sonnet-20240229"
    
    def chat(self, messages: list, context: str = None) -> str:
        messages = self.build_messages_with_context(messages, context)
        
        # Claude API需要分离system消息
        system_content = None
        converted_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                converted_messages.append(msg)
        
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": converted_messages,
            "max_tokens": self.config.max_tokens
        }
        
        if system_content:
            data["system"] = system_content
        
        response = requests.post(
            f"{self.api_base}/v1/messages",
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        result = response.json()
        return result["content"][0]["text"]
    
    def stream_chat(self, messages: list, context: str = None) -> Generator[str, None, None]:
        messages = self.build_messages_with_context(messages, context)
        
        system_content = None
        converted_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                converted_messages.append(msg)
        
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": converted_messages,
            "max_tokens": self.config.max_tokens,
            "stream": True
        }
        
        if system_content:
            data["system"] = system_content
        
        response = requests.post(
            f"{self.api_base}/v1/messages",
            headers=headers,
            json=data,
            stream=True,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith("data: "):
                    line = line[6:]
                    try:
                        data = json.loads(line)
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield text
                    except json.JSONDecodeError:
                        continue


class OllamaClient(BaseLLMClient):
    """Ollama本地模型客户端"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "http://localhost:11434"
        self.model = config.model or "llama2"
    
    def chat(self, messages: list, context: str = None) -> str:
        messages = self.build_messages_with_context(messages, context)
        
        data = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens
            }
        }
        
        response = requests.post(
            f"{self.api_base}/api/chat",
            json=data,
            timeout=120
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        result = response.json()
        return result["message"]["content"]
    
    def stream_chat(self, messages: list, context: str = None) -> Generator[str, None, None]:
        messages = self.build_messages_with_context(messages, context)
        
        data = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens
            }
        }
        
        response = requests.post(
            f"{self.api_base}/api/chat",
            json=data,
            stream=True,
            timeout=120
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if "message" in data:
                        content = data["message"].get("content", "")
                        if content:
                            yield content
                except json.JSONDecodeError:
                    continue


class ZhipuClient(BaseLLMClient):
    """智谱AI客户端 (GLM系列)"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "https://open.bigmodel.cn/api/paas/v4"
        self.model = config.model or "glm-4"
    
    def chat(self, messages: list, context: str = None) -> str:
        messages = self.build_messages_with_context(messages, context)
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens
        }
        
        response = requests.post(
            f"{self.api_base}/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    def stream_chat(self, messages: list, context: str = None) -> Generator[str, None, None]:
        messages = self.build_messages_with_context(messages, context)
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True
        }
        
        response = requests.post(
            f"{self.api_base}/chat/completions",
            headers=headers,
            json=data,
            stream=True,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"API请求失败: {response.status_code} - {response.text}")
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith("data: "):
                    line = line[6:]
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue


# ==================== 工厂函数 ====================

def create_llm_client(config: Dict[str, Any]) -> BaseLLMClient:
    """
    创建LLM客户端
    
    Args:
        config: 配置字典，包含:
            - provider: 模型提供商 (openai, qwen, wenxin, deepseek, claude, ollama, zhipu)
            - api_key: API密钥
            - api_base: 自定义API地址 (可选)
            - model: 模型名称 (可选)
            - temperature: 温度参数 (可选，默认0.7)
            - max_tokens: 最大token数 (可选，默认2000)
            - secret_key: 百度API Secret Key (文心一言必需)
    
    Returns:
        BaseLLMClient: LLM客户端实例
    """
    provider = config.get("provider", "").lower()
    
    llm_config = LLMConfig(
        provider=provider,
        api_key=config.get("api_key", ""),
        api_base=config.get("api_base"),
        model=config.get("model"),
        temperature=float(config.get("temperature", 0.7)),
        max_tokens=int(config.get("max_tokens", 2000)),
        secret_key=config.get("secret_key")
    )
    
    clients = {
        "openai": OpenAIClient,
        "qwen": QwenClient,
        "wenxin": WenxinClient,
        "deepseek": DeepSeekClient,
        "claude": ClaudeClient,
        "ollama": OllamaClient,
        "zhipu": ZhipuClient,
    }
    
    client_class = clients.get(provider)
    
    if not client_class:
        raise ValueError(f"不支持的模型提供商: {provider}，支持的提供商: {list(clients.keys())}")
    
    return client_class(llm_config)


# ==================== 模型信息 ====================

PROVIDER_INFO = {
    "openai": {
        "name": "OpenAI",
        "description": "GPT系列模型",
        "models": ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini"],
        "default_model": "gpt-3.5-turbo",
        "requires_secret_key": False,
        "api_base_hint": "https://api.openai.com/v1 (可自定义代理地址)"
    },
    "qwen": {
        "name": "通义千问",
        "description": "阿里云通义千问大模型",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max"],
        "default_model": "qwen-turbo",
        "requires_secret_key": False,
        "api_base_hint": "https://dashscope.aliyuncs.com/api/v1"
    },
    "wenxin": {
        "name": "文心一言",
        "description": "百度文心大模型",
        "models": ["ernie-bot", "ernie-bot-turbo", "ernie-bot-4"],
        "default_model": "ernie-bot-turbo",
        "requires_secret_key": True,
        "api_base_hint": "无需填写，使用百度官方API"
    },
    "deepseek": {
        "name": "DeepSeek",
        "description": "深度求索大模型",
        "models": ["deepseek-chat", "deepseek-coder"],
        "default_model": "deepseek-chat",
        "requires_secret_key": False,
        "api_base_hint": "https://api.deepseek.com"
    },
    "claude": {
        "name": "Claude",
        "description": "Anthropic Claude系列",
        "models": ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307", "claude-3-5-sonnet-20240620"],
        "default_model": "claude-3-sonnet-20240229",
        "requires_secret_key": False,
        "api_base_hint": "https://api.anthropic.com"
    },
    "ollama": {
        "name": "Ollama",
        "description": "本地运行的开源模型",
        "models": ["llama2", "llama3", "mistral", "qwen2", "deepseek-coder"],
        "default_model": "llama2",
        "requires_secret_key": False,
        "api_base_hint": "http://localhost:11434"
    },
    "zhipu": {
        "name": "智谱AI",
        "description": "GLM系列大模型",
        "models": ["glm-4", "glm-4-air", "glm-3-turbo"],
        "default_model": "glm-4",
        "requires_secret_key": False,
        "api_base_hint": "https://open.bigmodel.cn/api/paas/v4"
    }
}


def get_provider_info() -> Dict[str, Any]:
    """获取所有模型提供商信息"""
    return PROVIDER_INFO

