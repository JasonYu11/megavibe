from __future__ import annotations


BOT_COMMANDS = [
    {"command": "start", "description": "打开交易面板"},
    {"command": "status", "description": "查看运行状态"},
    {"command": "balance", "description": "查看钱包余额"},
    {"command": "quote", "description": "查询报价"},
    {"command": "buy", "description": "市价买入"},
    {"command": "sell", "description": "市价卖出"},
    {"command": "limit_buy", "description": "限价买入"},
    {"command": "limit_sell", "description": "限价卖出"},
    {"command": "orders", "description": "当前订单"},
    {"command": "history", "description": "历史订单"},
    {"command": "order", "description": "订单详情"},
    {"command": "cancel", "description": "取消订单"},
    {"command": "trade", "description": "流程引导交易"},
    {"command": "copy_add", "description": "添加跟单地址"},
    {"command": "copy_set", "description": "设置跟单比例和上限"},
    {"command": "copy_list", "description": "跟单列表"},
    {"command": "copy_status", "description": "跟单状态"},
    {"command": "copy_pause", "description": "暂停跟单"},
    {"command": "copy_resume", "description": "恢复跟单"},
    {"command": "copy_remove", "description": "删除跟单"},
    {"command": "mode", "description": "查看运行模式"},
    {"command": "help", "description": "查看命令说明"},
]
