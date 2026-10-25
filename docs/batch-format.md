# 完整批次格式

每个栏目独立组成 5 篇的批次。`topic` 为 `credit-cards` 或 `north-america-life`。两个栏目在同一期应去重，同一个作者不应占据多条；这些属于选题核验，工具不把相关性判断伪装成算法热榜。

```json
{
  "topic": "credit-cards",
  "date": "2026-10-24",
  "period_start": "2026-10-18",
  "period_end": "2026-10-24",
  "mode": "weekly-backfill",
  "selection": "来源检索范围与选择口径",
  "posts": [
    {
      "id": "真实的24位帖子ID",
      "title": "详情页标题",
      "author": "作者昵称",
      "author_id": "作者ID",
      "url": "https://www.xiaohongshu.com/explore/真实帖子ID",
      "body": "采集到的原帖正文",
      "summary": "人工整理的摘要",
      "imageSummary": "配图内容摘要",
      "date": "详情页日期原文",
      "published_date": "2026-10-20",
      "publication_basis": "detail-page",
      "capturedAt": "2026-10-25T00:00:00Z",
      "keywords": ["信用卡福利"],
      "likes": 100,
      "saves": 70,
      "comments": 15,
      "type": "image",
      "files": ["images/帖子ID-cover.webp", "images/帖子ID-1.webp"]
    }
  ]
}
```

上面只展示一条格式示例，不能直接作为完整批次导入。实际 `posts` 必须包含 5 篇不同的真实帖子。

`published_date` 使用首次发布时间，按配置时区换算后记录；`date` 则原样保存页面可见日期（可能含“编辑于”）。周 demo 的日期范围必须覆盖每篇帖子的首次发布日期。对于视频，`body` 是发布文案，除非另行完成转录，不能称为视频全文。

图片路径相对于批次 JSON 文件夹。文件必须已存在；工具不在导入阶段请求任意远程图片。GCS 上传时会根据内容指纹去重，临时图片 URL 不会成为长期数据依赖。

公开 demo 应由私人内容库导出：正文替换为原创摘要，清除原图文件及带临时参数的来源链接，保留原帖标题、作者、发布日期、采集时间、互动数字和规范来源链接。
