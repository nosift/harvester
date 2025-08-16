#!/usr/bin/env python3

"""
Core Tasks - Task Definition and Result Types

This module defines the core task types and result structures used throughout
the pipeline system. These provide type-safe task definitions and results.
"""

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, TypedDict

from .models import Service


class ProviderTaskSerialized(TypedDict):
    """Typed structure for serialized ProviderTask"""

    type: str  # Class name
    task_id: str
    provider: str
    created_at: float
    attempts: int
    data: Mapping[str, Any]  # Task-specific data


@dataclass
class ProviderTask(ABC):
    """Base class for all provider-specific tasks

    Abstract base class that defines the common interface and behavior
    for all tasks in the pipeline system. Each task carries provider
    identification for proper routing and result isolation.
    """

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider: str = ""  # Provider name for routing and isolation
    created_at: float = field(default_factory=time.time)
    attempts: int = 0

    def to_dict(self) -> ProviderTaskSerialized:
        """Serialize task to dictionary for persistence"""
        return ProviderTaskSerialized(
            type=self.__class__.__name__,
            task_id=self.task_id,
            provider=self.provider,
            created_at=self.created_at,
            attempts=self.attempts,
            data=self._serialize_data(),
        )

    @classmethod
    def from_dict(cls, data: ProviderTaskSerialized) -> "ProviderTask":
        """Deserialize task from dictionary"""
        instance = cls.__new__(cls)
        instance.task_id = data["task_id"]
        instance.provider = data["provider"]
        instance.created_at = data["created_at"]
        instance.attempts = data["attempts"]
        instance._deserialize_data(data["data"])
        return instance

    @abstractmethod
    def _serialize_data(self) -> Dict[str, Any]:
        """Serialize task-specific data"""
        pass

    @abstractmethod
    def _deserialize_data(self, data: Dict[str, Any]) -> None:
        """Deserialize task-specific data"""
        pass

    def increment_attempts(self) -> None:
        """Increment attempt counter"""
        self.attempts += 1

    def get_age_seconds(self) -> float:
        """Get task age in seconds"""
        return time.time() - self.created_at

    def is_expired(self, max_age_seconds: float) -> bool:
        """Check if task has exceeded maximum age"""
        return self.get_age_seconds() > max_age_seconds


@dataclass
class SearchTask(ProviderTask):
    """Task for searching GitHub for potential API keys"""

    query: str = ""
    regex: str = ""
    page: int = 1
    use_api: bool = False
    address_pattern: str = ""
    endpoint_pattern: str = ""
    model_pattern: str = ""

    def _serialize_data(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "regex": self.regex,
            "page": self.page,
            "use_api": self.use_api,
            "address_pattern": self.address_pattern,
            "endpoint_pattern": self.endpoint_pattern,
            "model_pattern": self.model_pattern,
        }

    def _deserialize_data(self, data: Dict[str, Any]) -> None:
        self.query = data["query"]
        self.regex = data.get("regex", "")
        self.page = data["page"]
        self.use_api = data.get("use_api", False)
        self.address_pattern = data.get("address_pattern", "")
        self.endpoint_pattern = data.get("endpoint_pattern", "")
        self.model_pattern = data.get("model_pattern", "")

    def get_search_term(self) -> str:
        """Get the primary search term"""
        return self.query or self.regex


@dataclass
class AcquisitionTask(ProviderTask):
    """Task for acquiring API keys from discovered URLs"""

    url: str = ""
    key_pattern: str = ""
    retries: int = 3
    address_pattern: str = ""
    endpoint_pattern: str = ""
    model_pattern: str = ""

    def _serialize_data(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "key_pattern": self.key_pattern,
            "retries": self.retries,
            "address_pattern": self.address_pattern,
            "endpoint_pattern": self.endpoint_pattern,
            "model_pattern": self.model_pattern,
        }

    def _deserialize_data(self, data: Dict[str, Any]) -> None:
        self.url = data["url"]
        self.key_pattern = data["key_pattern"]
        self.retries = data.get("retries", 3)
        self.address_pattern = data.get("address_pattern", "")
        self.endpoint_pattern = data.get("endpoint_pattern", "")
        self.model_pattern = data.get("model_pattern", "")


@dataclass
class CheckTask(ProviderTask):
    """Task for validating API keys"""

    service: Service = field(default_factory=Service)
    custom_url: str = ""
    retries: int = 3

    def _serialize_data(self) -> Dict[str, Any]:
        return {
            "service": self.service.to_dict(),
            "custom_url": self.custom_url,
            "retries": self.retries,
        }

    def _deserialize_data(self, data: Dict[str, Any]) -> None:
        self.service = Service.from_dict(data["service"])
        self.custom_url = data.get("custom_url", "")
        self.retries = data.get("retries", 3)


@dataclass
class InspectTask(ProviderTask):
    """Task for inspecting API capabilities"""

    service: Service = field(default_factory=Service)
    custom_url: str = ""
    retries: int = 3

    def _serialize_data(self) -> Dict[str, Any]:
        return {
            "service": self.service.to_dict(),
            "custom_url": self.custom_url,
            "retries": self.retries,
        }

    def _deserialize_data(self, data: Dict[str, Any]) -> None:
        self.service = Service.from_dict(data["service"])
        self.custom_url = data.get("custom_url", "")
        self.retries = data.get("retries", 3)


@dataclass
class SearchTaskResult:
    """Result from search task execution"""

    links: List[str] = field(default_factory=list)
    total: Optional[int] = None

    def is_successful(self) -> bool:
        """Check if search was successful"""
        return len(self.links) > 0

    def get_summary(self) -> str:
        """Get result summary"""
        return f"Found {len(self.links)} links" + (f" out of {self.total}" if self.total else "")


@dataclass
class AcquisitionTaskResult:
    """Result from acquisition task execution"""

    services: List[Service] = field(default_factory=list)

    def is_successful(self) -> bool:
        """Check if collection was successful"""
        return len(self.services) > 0

    def get_summary(self) -> str:
        """Get result summary"""
        return f"Collected {len(self.services)} services"


@dataclass
class CheckTaskResult:
    """Result from check task execution"""

    valid: List[Service] = field(default_factory=list)
    invalid: List[Service] = field(default_factory=list)
    no_quota: List[Service] = field(default_factory=list)
    wait_check: List[Service] = field(default_factory=list)

    def count(self) -> int:
        """Get total number of keys processed"""
        return len(self.valid) + len(self.invalid) + len(self.no_quota) + len(self.wait_check)

    def get_success_rate(self) -> float:
        """Get success rate of key validation"""
        total = self.count()
        return len(self.valid) / total if total > 0 else 0.0

    def get_summary(self) -> str:
        """Get result summary"""
        return f"Checked {self.count()} keys: {len(self.valid)} valid, {len(self.invalid)} invalid"


@dataclass
class InspectTaskResult:
    """Result from inspect task execution"""

    models: List[str] = field(default_factory=list)

    def is_successful(self) -> bool:
        """Check if models listing was successful"""
        return len(self.models) > 0

    def get_summary(self) -> str:
        """Get result summary"""
        return f"Found {len(self.models)} models"
