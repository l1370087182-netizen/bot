import re

with open('D:\\binance_bot\\bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复导入块 - 使用正则匹配
pattern = r'# 可选模块.*?print\(".*?未找到，使用简化模式"\)'
replacement = 'RiskManager = None\ntrade_recorder = None'
content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open('D:\\binance_bot\\bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('修复完成')
