"""数据提供方接口（预留在线地图 API 接入点）。

当前默认使用本地 JSON 城市库（CityLibrary）。
如需接入高德/百度/GTFS 等在线数据，请实现 DataProvider 并返回 City 对象，
即可在不改动核心规划与 PDF 导出逻辑的前提下获得实时数据。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.models import City


class DataProvider(ABC):
    """统一数据适配层接口。"""

    name: str = "base"

    @abstractmethod
    def fetch_city(self, city_name: str) -> City:
        """拉取某城市的线路库，返回 City 对象。"""
        raise NotImplementedError

    @abstractmethod
    def available_cities(self) -> list[str]:
        """返回可提供的城市列表。"""
        raise NotImplementedError


class LocalJsonProvider(DataProvider):
    """本地 JSON 城市库提供方。"""

    name = "local-json"

    def __init__(self, data_dir: str):
        from ..core.models import CityLibrary
        self.lib = CityLibrary(data_dir)

    def available_cities(self) -> list[str]:
        return self.lib.list_cities()

    def fetch_city(self, city_name: str) -> City:
        return self.lib.load(city_name)
