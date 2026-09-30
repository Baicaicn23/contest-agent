"""联网搜索与网页读取：Bing 中国版实现 SearchPort（P5）。

为什么选 Bing 中国版（cn.bing.com）？
- 国内直连可达（Google/DuckDuckGo 都不可达）；
- 无需申请 API 密钥——P6 的验收标准是"同学 10 分钟跑通"，多一个密钥就多一道坎；
- 结果页是静态 HTML，可以解析（代价：Bing 改版时选择器要跟着改，
  所以解析选择器集中在 _parse_bing_results 一个函数里，改起来只动一处）。

"带降级"是本模块的纪律（对应 SearchPort 的约定）：
搜索失败返回空列表、读网页失败返回说明文字、链接校验失败返回 (False, 原因)——
任何网络意外都不允许抛异常炸掉上层流程。
"""

from __future__ import annotations

import urllib.parse

import requests
from bs4 import BeautifulSoup

from ...settings import SearchConfig

# 伪装成正常浏览器：Bing 对无 UA / 脚本 UA 的请求会返回风控页
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT_SECONDS = 12


def _parse_bing_results(html: str) -> list[dict]:
    """解析 Bing 结果页 HTML，提取 [{title, url, snippet}]（纯函数，可离线测试）。"""
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for item in soup.select("li.b_algo"):
        link = item.select_one("h2 a")
        if link is None or not link.get("href"):
            continue  # 没有链接的条目（广告位/推荐位）跳过
        snippet_el = item.select_one(".b_caption p") or item.select_one("p")
        results.append(
            {
                "title": link.get_text(strip=True),
                "url": link["href"],
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
    return results


def _parse_so360_results(html: str) -> list[dict]:
    """解析 360 搜索结果页 HTML（作为 Bing 被风控时的回退引擎）。

    360 的结果条目在 li.res-list 里；真实网址藏在链接的 data-mdurl
    属性里（href 是 360 的跳转包装链接），优先取前者。
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for item in soup.select("li.res-list"):
        link = item.select_one("h3 a")
        if link is None:
            continue
        url = link.get("data-mdurl") or link.get("href") or ""
        if not url.startswith("http"):
            continue
        snippet_el = item.select_one("p.res-desc") or item.select_one("p")
        results.append(
            {
                "title": link.get_text(strip=True),
                "url": url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
    return results


def _html_to_text(html: str) -> str:
    """网页 HTML -> 干净正文文本（去脚本/样式/空行）。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


class BingSearch:
    """用 Bing 中国版实现 SearchPort 的三个能力：搜索、读网页、验证链接。"""

    def __init__(self, config: SearchConfig):
        self.config = config

    # ---------- 能力一：搜索 ----------

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """搜索并返回 [{title, url, snippet}]；全部引擎都失败才降级为空列表。

        多引擎回退链：Bing（主）→ 360（备）。搜索引擎对自动化请求
        时而会弹风控页（表现为"200 但 0 条结果"），单引擎不可靠，
        一个失败自动换下一个，哪个能用用哪个。
        """
        top_k = top_k or self.config.max_results
        engines = [
            (self.config.engine_url, _parse_bing_results),
        ]
        if self.config.fallback_engine_url:
            engines.append((self.config.fallback_engine_url, _parse_so360_results))

        for template, parse in engines:
            try:
                # quote_plus 把中文搜索词转成 URL 能接受的编码（如"蓝桥杯"->%E8%93%9D...）
                url = template.format(query=urllib.parse.quote_plus(query))
                resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=TIMEOUT_SECONDS)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                results = parse(resp.text)[:top_k]
                if results:
                    return results  # 这个引擎可用，直接用它的结果
                # 200 但 0 条结果 = 大概率是风控页，换下一个引擎
            except requests.RequestException:
                continue  # 这个引擎网络失败，换下一个
        return []  # 全部引擎失败：降级为空列表

    # ---------- 能力二：读网页 ----------

    def read_page(self, url: str, max_chars: int = 3000) -> str:
        """读取网页正文文本（截断），失败返回说明文字。"""
        try:
            resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            text = _html_to_text(resp.text)
            if not text:
                return "页面能打开但没有正文（可能是图片/视频页）。"
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n…（正文过长，已截断，原文共 {len(text)} 字）"
            return text
        except requests.RequestException as error:
            return f"网页读取失败：{error}"

    # ---------- 能力三：验证链接（引用存在性校验的底层） ----------

    def check_url(self, url: str) -> tuple[bool, str]:
        """验证链接是否真实存在。判定尺度见 SearchPort.check_url 的说明。"""
        try:
            resp = requests.get(
                url, headers={"User-Agent": BROWSER_UA}, timeout=TIMEOUT_SECONDS, allow_redirects=True
            )
        except requests.RequestException as error:
            return False, f"无法访问（{error.__class__.__name__}）"

        if resp.status_code in (403, 405, 429):
            # 页面存在但拒绝机器人访问：算存在，注明原因
            return True, f"页面存在但拒绝机器人访问（HTTP {resp.status_code}）"
        if resp.status_code < 400:
            return True, f"正常（HTTP {resp.status_code}）"
        return False, f"HTTP {resp.status_code}"
