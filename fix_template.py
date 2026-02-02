"""修复模板文件中的大括号转义"""
from pathlib import Path

template_file = Path("templates/impl.py.template")
content = template_file.read_text(encoding='utf-8')

# 保护占位符
content = content.replace('{ENGINE_VERSION}', '___ENGINE_VERSION___')
content = content.replace('{KB_PATH}', '___KB_PATH___')

# 转义所有大括号
content = content.replace('{', '{{').replace('}', '}}')

# 恢复占位符
content = content.replace('___ENGINE_VERSION___', '{ENGINE_VERSION}')
content = content.replace('___KB_PATH___', '{KB_PATH}')

# 保存
template_file.write_text(content, encoding='utf-8')
print(f"已修复: {template_file}")
