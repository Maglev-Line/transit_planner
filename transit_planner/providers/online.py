# -*- coding: utf-8 -*-
"""在线地图 API 数据提供方（高德 / 百度 / 腾讯）。

仅获取『线路信息』（经停站、首末班车时间、线路名称等），**不获取实时状态**。
所有请求均为尽力而为：未配置 key、网络异常、接口返回格式变化时，会抛出
OnlineProviderError，由界面优雅降级（继续使用本地 JSON 数据 / 手动输入）。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from ..core.models import Line, TYPE_BUS, TYPE_METRO

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) 运转计划助手/1.1"}


class OnlineProviderError(Exception):
    """在线数据获取失败。message 面向用户，可直接弹窗提示。"""


def _http_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _build_line(name: str, stations: list[str], first: str = "", last: str = "",
                prefix: str = "api") -> Line | None:
    """根据 API 返回的线路名/站点/首末班构造 Line 对象。"""
    name = (name or "").strip()
    if not name or not stations:
        return None
    seen: list[str] = []
    for s in stations:
        s = (s or "").strip()
        if s and s not in seen:
            seen.append(s)
    if len(seen) < 2:
        return None
    ltype = TYPE_METRO if "地铁" in name or "轨交" in name else TYPE_BUS
    line = Line(
        id=f"{prefix}_{name}", name=name, type=ltype,
        stations=seen,
        first_train=(first or "").strip(), last_train=(last or "").strip(),
    )
    # API 未提供站间时长：给默认估算值（3 分钟/站），保证能计算运行时长
    line.travel_minutes = [3.0] * (len(seen) - 1)
    return line


class BaseMapProvider(ABC):
    """在线地图数据提供方基类。"""

    name = "base"
    display_name = "在线地图"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = (api_key or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _require_key(self) -> None:
        if not self.configured:
            raise OnlineProviderError(f"{self.display_name}地图：尚未在「设置」中配置 API Key")

    @abstractmethod
    def search_lines(self, city: str, keyword: str, limit: int = 8) -> list[Line]:
        """按线路名关键词查询线路（经停站、首末班等）。"""
        raise NotImplementedError

    @abstractmethod
    def search_stations(self, city: str, keyword: str = "", limit: int = 20) -> list[str]:
        """按关键词查询站点名称（用于站点下拉补全）。"""
        raise NotImplementedError


# ---------------- 高德 ----------------
class AmapProvider(BaseMapProvider):
    name = "amap"
    display_name = "高德"

    def search_lines(self, city: str, keyword: str, limit: int = 8) -> list[Line]:
        self._require_key()
        url = "https://restapi.amap.com/v3/bus/linename?" + urllib.parse.urlencode({
            "key": self.api_key, "city": city, "offset": limit, "output": "json",
            "extensions": "all",
        })
        try:
            data = _http_json(url)
        except Exception as ex:
            raise OnlineProviderError(f"高德API请求失败（请检查网络）：{ex}") from ex
        if str(data.get("status")) != "1":
            raise OnlineProviderError(f"高德API返回错误：{data.get('info', '未知')}")
        lines: list[Line] = []
        for bl in data.get("buslines", []) or []:
            stations: list[str] = []
            for key_ in ("busstops", "stations", "stop"):
                for s in bl.get(key_, []) or []:
                    sn = (s.get("name") or "").strip()
                    if sn:
                        stations.append(sn)
                if stations:
                    break
            ln = _build_line(bl.get("name", ""), stations,
                             bl.get("start_time", ""), bl.get("end_time", ""),
                             prefix="amap")
            if ln is not None:
                lines.append(ln)
        return lines

    def search_stations(self, city: str, keyword: str = "", limit: int = 20) -> list[str]:
        self._require_key()
        url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode({
            "key": self.api_key, "keywords": keyword, "city": city, "citylimit": "true",
            "offset": limit, "output": "json",
        })
        try:
            data = _http_json(url)
        except Exception as ex:
            raise OnlineProviderError(f"高德API请求失败（请检查网络）：{ex}") from ex
        if str(data.get("status")) != "1":
            raise OnlineProviderError(f"高德API返回错误：{data.get('info', '未知')}")
        out: list[str] = []
        for poi in data.get("pois", []) or []:
            nm = (poi.get("name") or "").strip()
            if nm and nm not in out:
                out.append(nm)
        return out


# ---------------- 百度 ----------------
class BaiduProvider(BaseMapProvider):
    name = "baidu"
    display_name = "百度"

    def search_lines(self, city: str, keyword: str, limit: int = 8) -> list[Line]:
        # 百度地图未提供稳定的公交/地铁线路查询 REST 接口，明确提示改用其他源
        raise OnlineProviderError(
            "百度地图暂未开放稳定的公交/地铁线路查询接口，请在「设置」中改用高德或腾讯。")

    def search_stations(self, city: str, keyword: str = "", limit: int = 20) -> list[str]:
        self._require_key()
        url = "https://api.map.baidu.com/place/v2/search?" + urllib.parse.urlencode({
            "q": keyword, "region": city, "output": "json", "ak": self.api_key,
            "scope": "2", "page_size": limit,
        })
        try:
            data = _http_json(url)
        except Exception as ex:
            raise OnlineProviderError(f"百度API请求失败（请检查网络）：{ex}") from ex
        if str(data.get("status")) != "0":
            raise OnlineProviderError(f"百度API返回错误：{data.get('message', '未知')}")
        out: list[str] = []
        for res in data.get("results", []) or []:
            nm = (res.get("name") or "").strip()
            if nm and nm not in out:
                out.append(nm)
        return out


# ---------------- 腾讯 ----------------
class TencentProvider(BaseMapProvider):
    name = "tencent"
    display_name = "腾讯"

    def search_lines(self, city: str, keyword: str, limit: int = 8) -> list[Line]:
        raise OnlineProviderError(
            "腾讯地图暂未开放稳定的公交/地铁线路查询接口，请在「设置」中改用高德。")

    def search_stations(self, city: str, keyword: str = "", limit: int = 20) -> list[str]:
        self._require_key()
        url = "https://apis.map.qq.com/ws/place/v1/search?" + urllib.parse.urlencode({
            "keyword": keyword, "region": city, "page_size": limit, "key": self.api_key,
        })
        try:
            data = _http_json(url)
        except Exception as ex:
            raise OnlineProviderError(f"腾讯API请求失败（请检查网络）：{ex}") from ex
        if str(data.get("status")) != "0":
            raise OnlineProviderError(f"腾讯API返回错误：{data.get('message', '未知')}")
        out: list[str] = []
        for poi in data.get("data", []) or []:
            nm = (poi.get("title") or poi.get("address") or "").strip()
            if nm and nm not in out:
                out.append(nm)
        return out


PROVIDER_CLASSES = {
    "amap": AmapProvider,
    "baidu": BaiduProvider,
    "tencent": TencentProvider,
}


def build_providers(settings) -> list[BaseMapProvider]:
    """根据设置返回已启用的数据提供方实例（按启用顺序）。"""
    out: list[BaseMapProvider] = []
    if settings is None:
        return out
    for key in settings.enabled_providers:
        cls = PROVIDER_CLASSES.get(key)
        if cls is None:
            continue
        api_key = getattr(settings, f"{key}_key", "")
        out.append(cls(api_key))
    return out
