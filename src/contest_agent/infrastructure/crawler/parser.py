"""纯解析函数：HTML 文本进，结构化数据出，全程不发任何网络请求。

把"解析"和"抓取"拆成两个文件是刻意的设计：
- 解析不碰网络 -> 可以拿保存下来的真实页面样本（tests/fixtures/）反复测，
  又快又稳，断网也能跑测试；
- 抓取只管下载 HTML -> 拿到后交给本文件的函数解析。
两边各测各的，出了问题一眼能定位是"网页变了"还是"网络挂了"。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ...domain.entities import Notice

# 带这些后缀的链接，视为"附件"（详情页正文里的 pdf/doc/压缩包等）
ATTACHMENT_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar",
)


def parse_list_page(html: str, base_url: str, selectors: dict[str, str]) -> list[Notice]:
    """解析列表页 HTML，返回页面上的全部通知（半成品：还没有正文）。

    逐条容错：某一条的 HTML 缺胳膊少腿（比如没有标题）时，
    跳过这一条继续解析下一条，而不是让整页失败——
    网站编辑手滑是很常见的事，不能因为一条脏数据丢掉另外七条。
    """
    soup = BeautifulSoup(html, "html.parser")
    notices: list[Notice] = []
    for item in soup.select(selectors["item"]):
        try:
            notices.append(_parse_list_item(item, base_url, selectors))
        except (ValueError, TypeError, KeyError):
            # 一条失败就跳过。真正的爬虫系统这里会记日志，我们的版本注释说明即可
            continue
    return notices


def parse_detail_page(
    html: str, base_url: str, selectors: dict[str, str], notice: Notice
) -> Notice:
    """解析详情页 HTML，把标题、正文、附件补进传入的 notice 对象后返回。

    沿用列表页传进来的对象（而不是新建）：调用方能感觉到
    "这是同一条通知被补全了"，符合 NoticeSourcePort.fetch_detail 的约定。
    """
    soup = BeautifulSoup(html, "html.parser")

    # 标题：详情页的标题通常比列表页更完整（列表页可能被截断），优先用详情页的
    title_el = soup.select_one(selectors["detail_title"])
    if title_el is not None:
        notice.title = title_el.get_text(strip=True)

    # 正文：只提取纯文本（去掉 HTML 标签和行内样式），
    # P2 的 LLM 识别只需要文字内容，不需要排版
    content_el = soup.select_one(selectors["detail_content"])
    if content_el is None:
        raise ValueError(f"详情页里找不到正文容器（选择器：{selectors['detail_content']}）")
    notice.content = _extract_text(content_el)

    # 附件：正文区域里指向文件后缀的链接
    notice.attachments = _extract_attachments(content_el, base_url)
    return notice


def _parse_list_item(
    item: Tag, base_url: str, selectors: dict[str, str]
) -> Notice:
    """解析列表页里的单个条目（div）。字段不全就抛异常，由调用方跳过。"""
    link_el = item.select_one(selectors["link"])
    title_el = item.select_one(selectors["title"])
    if link_el is None or title_el is None:
        raise ValueError("条目缺少标题或链接，跳过")

    return Notice(
        # href 往往是相对路径（/szxy/c/...），urljoin 负责拼成完整网址
        source_url=urljoin(base_url, link_el["href"]),
        title=title_el.get_text(strip=True),
        published_at=_parse_item_date(item, selectors),
    )


def _parse_item_date(item: Tag, selectors: dict[str, str]) -> datetime | None:
    """把条目里拆成两半的日期（"2026" + "09-29"）拼回 datetime。

    这个网站的模板把年放在一个 span、月-日放在另一个 span。
    解析失败返回 None——日期缺失不该让整条通知作废。
    """
    year_el = item.select_one(selectors["year"])
    month_day_el = item.select_one(selectors["month_day"])
    if year_el is None or month_day_el is None:
        return None
    raw = f"{year_el.get_text(strip=True)}-{month_day_el.get_text(strip=True)}"
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _extract_text(element: Tag) -> str:
    """把一个 HTML 元素变成干净的纯文本：去标签、去脚本、去空行。"""
    # script/style 标签里的内容不是正文（多是代码和样式定义），先整个删掉
    for tag in element(["script", "style"]):
        tag.decompose()
    # get_text(分隔符) 会把所有文字按标签边界拆开；
    # 再逐行去掉首尾空白、丢掉空行，得到干净的正文
    lines = (line.strip() for line in element.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def _extract_attachments(element: Tag, base_url: str) -> list[str]:
    """收集正文区域里的附件链接（指向 pdf/doc/压缩包等的 <a>）。"""
    attachments: list[str] = []
    for a in element.find_all("a", href=True):
        href = a["href"].lower()
        if href.startswith(("mailto:", "javascript:", "#")):
            continue  # 这些不是文件链接
        # split("?") 是为了去掉链接问号后面的参数，只看文件名部分的后缀
        if href.split("?")[0].endswith(ATTACHMENT_SUFFIXES):
            attachments.append(urljoin(base_url, a["href"]))
    return attachments
