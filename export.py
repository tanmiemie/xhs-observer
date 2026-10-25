"""Portable optional Excel export for installs outside the authoring environment."""
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo


def workbook_bytes(archive):
    import xlsxwriter
    output = BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    header = book.add_format({"bold": True, "bg_color": "#385E49", "font_color": "white", "valign": "vcenter"})
    text = book.add_format({"valign": "top", "text_wrap": True})
    timestamp = book.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"})
    posts = list(archive["posts"].values())

    def sheet(name, headings, rows, widths):
        ws = book.add_worksheet(name)
        ws.hide_gridlines(2)
        ws.freeze_panes(1, 2)
        ws.set_row(0, 26)
        for col, title in enumerate(headings):
            ws.write(0, col, title, header)
            ws.set_column(col, col, widths[col])
        for row, values in enumerate(rows, 1):
            for col, value in enumerate(values):
                ws.write(row, col, value, text)
        if rows:
            ws.autofilter(0, 0, len(rows), len(headings) - 1)
        return ws

    sheet("帖子", ["帖子ID", "标题", "作者", "发布日期", "摘要", "原帖链接"], [[p["id"], p["title"], p["author"], p.get("published_date") or p.get("published_label", ""), p["summary"], p["source_url"]] for p in posts], [28, 48, 22, 20, 80, 65])
    sheet("正文存档", ["帖子ID", "标题", "正文", "原帖链接"], [[p["id"], p["title"], p["body"], p["source_url"]] for p in posts], [28, 48, 110, 65])
    snapshots = list(archive["snapshots"].values())
    metrics = sheet("互动记录", ["采集时间（洛杉矶）", "帖子ID", "标题", "点赞", "收藏", "评论", "总互动", "原帖链接"], [[datetime.fromisoformat(s["captured_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).replace(tzinfo=None), s["post_id"], s["content"]["title"], s["likes"], s["saves"], s["comments"], None, s["content"]["source_url"]] for s in snapshots], [26, 28, 48, 12, 12, 12, 12, 65])
    for index, s in enumerate(snapshots, 1):
        metrics.write_datetime(index, 0, datetime.fromisoformat(s["captured_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).replace(tzinfo=None), timestamp)
        metrics.write_formula(index, 6, f"=SUM(D{index+1}:F{index+1})", None, s["likes"] + s["saves"] + s["comments"])
    sheet("图片索引", ["帖子ID", "图片类型", "顺序", "文件索引", "原帖链接"], [[p["id"], m["role"], m["order"], archive["media"][m["id"]]["path"], p["source_url"] for p in posts for m in p["media"]], [28, 14, 10, 85, 65])
    book.close()
    return output.getvalue()
