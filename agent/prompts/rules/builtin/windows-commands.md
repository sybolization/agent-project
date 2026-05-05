<!-- scope: all -->
<!-- priority: 5 -->
<!-- description: Windows环境命令执行规则 -->

<rule name="windows-commands">
Windows环境下执行命令时，必须遵守以下规则：

1. **不要使用 && 链式命令**：Windows CMD不支持 && 链式命令，请分开执行
2. **不要使用 grep/awk/sed**：Windows没有这些Linux工具，请使用PowerShell替代
3. **路径使用引号包裹**：包含空格的路径必须用双引号包裹
4. **使用正斜杠或双反斜杠**：文件路径中使用正斜杠(/)或双反斜杠(\\)

正确示例：
- opencli xiaohongshu search "卷发棒" --limit 10 -f json
- opencli browser state

错误示例：
- opencli xiaohongshu search "卷发棒" && opencli browser state
- cat file.txt | grep "keyword"
</rule>
