<!-- scope: all -->
<!-- priority: 10 -->
<!-- description: 确保Agent使用完整URL，不截断查询参数 -->

<rule name="url-integrity">
使用 opencli browser open 打开网页时，必须遵守以下规则：

1. **使用完整URL**：始终使用命令返回的完整URL，包括所有查询参数
2. **不得截断URL**：不要删除或简化URL中的查询参数（如 xsec_token、token、sign 等）
3. **不得自行构造URL**：不要基于部分信息自行拼接URL
4. **查询参数至关重要**：URL中的查询参数通常用于安全验证，缺少参数会导致页面无法访问

正确示例：
- opencli browser open "https://www.xiaohongshu.com/search_result/xxx?xsec_token=AB_xxx&xsec_source=pc_search"
- opencli browser open "https://www.douyin.com/video/xxx?previous_page=web_search"

错误示例：
- opencli browser open "https://www.xiaohongshu.com/search_result/xxx" （缺少 xsec_token）
- opencli browser open "https://www.douyin.com/video/xxx" （缺少查询参数）
</rule>
